"""One media socket becomes one running call — inside a hooks-service process.

This is the only module in the worker package that imports the engine (and
through it pipecat). The hooks lifespan imports it before accepting traffic,
so import failures surface at startup and calls do not pay for a cold engine.
The media controller keeps its import local to avoid loading the engine when
only importing the routes.

The campaign script is rendered here, per attempt, from the inputs pinned on
the call row (in a thread, under the sandbox's caps — see
``utils/script.py``). A render failure fails the attempt rather than
running the agent without its script: an agent with no goal on a live line is
worse than a retry.

Status transitions are all on the *attempt* row and guarded in SQL, because
three writers race for it: this runner, the sweep, and the provider's status
webhook. The rules:

* ``in_progress`` is only entered from ``dialing``;
* ``completed`` is set only after a clean session end;
* ``failed`` never overwrites a terminal state — a disposition that arrived
  first (busy, canceled) is the truth, the pipeline error is noise after it.

The parent call's lifecycle is settled by the dispatcher, never here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import WebSocket
from loguru import logger

# Settings first: importing it runs the core Config.init, which the ORM
# base below requires. Keeps this module a safe import root (taskiq CLI,
# tests) regardless of who imports it first.
from src.settings import SETTINGS  # noqa: F401  isort: skip

from src.application.engine.config import CallContext, CustomerProfile, LanguageConfig
from src.application.engine.session import CallSession, SessionHooks
from src.application.services import analysis
from src.application.services.billing import BillingService
from src.application.services.messaging import MessagingService, SendError
from src.application.worker import registry
from src.common.enums.engine import CallStatusEnum
from src.core.db.session import SessionMaker
from src.integrations.telephony.base import build_telephony
from src.models.agent import VoiceAgent
from src.models.call import CallAttempt
from src.repositories.agent import VoiceAgentCRUD, build_agent_config
from src.repositories.call import CallAttemptCRUD
from src.repositories.telephony import TelephonyCRUD
from src.schemas.admin import SSmsSend
from src.utils.script import ScriptError, merge_player_attributes, render_script_async

#: States nothing may overwrite.
TERMINAL_STATUSES = frozenset(
    {
        CallStatusEnum.completed,
        CallStatusEnum.busy,
        CallStatusEnum.no_answer,
        CallStatusEnum.failed,
        CallStatusEnum.canceled,
        CallStatusEnum.rejected,
        CallStatusEnum.invalid_number,
    }
)

#: Live sessions in this process, for graceful drain on shutdown.
active_sessions: dict[str, CallSession] = {}


async def _set_status(
    org_uuid: str,
    attempt_id: int,
    status: CallStatusEnum,
    *,
    only_from: tuple[CallStatusEnum, ...],
    extra: dict[str, Any] | None = None,
) -> bool:
    """Guarded status transition; the WHERE clause is the race arbiter."""
    async with SessionMaker.get_session(org_uuid)() as session:
        updated = await CallAttemptCRUD(session).update(
            CallAttempt.id == attempt_id,
            CallAttempt.status.in_(only_from),
            data={"status": status, **(extra or {})},
        )
        await session.commit()
        return bool(updated)


async def run_media_call(websocket: WebSocket, *, org_uuid: str, call_id: int) -> None:
    """Run the attempt whose media socket just arrived, start to finish.

    Args:
        websocket: The accepted media connection.
        org_uuid: Organization whose database holds the attempt.
        call_id: The claimed attempt row's id (the registry's ``call_id`` is
            the attempt — the leg is what media sockets address).
    """
    attempt_id = call_id
    logger.info(f"attempt {attempt_id} in org {org_uuid}: run_media_call started")
    # One short session to load everything; nothing DB-bound is held while
    # the call runs — the engine stays infrastructure-free, per its contract.
    async with SessionMaker.get_session(org_uuid)() as session:
        attempt = await CallAttemptCRUD(session).get_one_or_none(
            CallAttempt.id == attempt_id
        )
        if attempt is None or attempt.status != CallStatusEnum.dialing:
            # Canceled or swept while the socket was in flight; nothing to run.
            logger.warning(
                f"media socket for attempt {attempt_id} in org {org_uuid} arrived in state "
                f"{attempt.status if attempt else 'missing'}; refusing"
            )
            await websocket.close(code=4404)
            return

        call_row = attempt.call
        agent_row = await VoiceAgentCRUD(session).get_one_or_none(
            VoiceAgent.id == call_row.agent_id
        )
        if agent_row is None or agent_row.telephony is None:
            await websocket.close(code=4500)
            await _set_status(
                org_uuid,
                attempt_id,
                CallStatusEnum.failed,
                only_from=(CallStatusEnum.dialing,),
                extra={
                    "error": "agent or telephony binding disappeared before media arrived"
                },
            )
            return

        attempt_uuid = str(attempt.uuid)
        agent_config = build_agent_config(agent_row)
        telephony_config = TelephonyCRUD.build_config(agent_row.telephony)
        # Read here, while the row is still attached: the send_sms closure
        # below runs long after this session is closed. None means "the
        # organization's single active route" — see ``VoiceAgent.messaging_id``.
        agent_messaging_id = agent_row.messaging_id

        client = call_row.client
        campaign = call_row.campaign

        merged_attributes = merge_player_attributes(
            call_row.attributes,
            player_id=call_row.player_id,
            vip_status=call_row.vip_status,
            last_deposit=call_row.last_deposit,
            last_active=call_row.last_active,
            country=call_row.country,
            timezone=call_row.timezone,
        )

        script: str | None = None
        if campaign is not None and campaign.call_script:
            try:
                script = await render_script_async(
                    campaign.call_script,
                    name=client.name if client else "",
                    bonuses=call_row.bonuses,
                    attributes=merged_attributes,
                )
            except ScriptError as exc:
                await websocket.close(code=4500)
                await _set_status(
                    org_uuid,
                    attempt_id,
                    CallStatusEnum.failed,
                    only_from=(CallStatusEnum.dialing,),
                    extra={"error": f"call_script render failed: {exc}"[:2000]},
                )
                return

        customer = None
        if client is not None:
            # Campaign calls: the rendered script is the one channel for client
            # facts — the profile layer keeps identity only, so the model never
            # sees the same fact twice in two formats. Manual calls have no
            # template, so attributes ride the profile layer instead.
            customer = CustomerProfile(
                customer_id=str(client.uuid),
                name=client.name,
                phone=client.phone,
                attributes={}
                if campaign is not None
                else {key: str(value) for key, value in merged_attributes.items()},
                offers=[analysis.offer_label(offer) for offer in call_row.bonuses],
            )

        context = CallContext(
            call_id=attempt_uuid,
            org_uuid=org_uuid,
            direction=call_row.direction,
            language=attempt.language or call_row.language,
            customer=customer,
            call_script=script,
            idle_timeout_seconds=client.idle_timeout_seconds
            if client is not None
            else None,
            overrides=LanguageConfig(**call_row.overrides)
            if call_row.overrides
            else None,
        )

    adapter = build_telephony(telephony_config, call_id=attempt_uuid)
    transport = await adapter.answer_media(websocket)
    logger.info(
        f"attempt {attempt_uuid}: telephony transport ready, starting session.prepare"
    )

    switch_events: list[dict[str, Any]] = []

    async def on_started(_call_id: str, _payload: dict[str, Any]) -> None:
        await _set_status(
            org_uuid,
            attempt_id,
            CallStatusEnum.in_progress,
            only_from=(CallStatusEnum.dialing,),
            extra={"answered_at": datetime.now()},
        )

    async def on_finished(_call_id: str, payload: dict[str, Any]) -> None:
        # Persist what was said and when it ended; the *status* is decided by
        # whoever wins the guarded transitions below — this hook also fires on
        # errors and cancellations, and must not declare success for them.
        async with SessionMaker.get_session(org_uuid)() as session:
            await CallAttemptCRUD(session).update(
                CallAttempt.id == attempt_id,
                data={
                    # The engine's context holds only what the model saw; the
                    # language-switch events recorded during the call are not
                    # in it, so they are re-attached rather than overwritten.
                    "messages": [*payload.get("messages", []), *switch_events],
                    "ended_at": datetime.now(),
                },
            )
            await session.commit()

    async def on_language_switch(_call_id: str, payload: dict[str, Any]) -> None:
        switch_events.append({"role": "event", **payload})
        async with SessionMaker.get_session(org_uuid)() as session:
            row = await CallAttemptCRUD(session).get_one_or_none(
                CallAttempt.id == attempt_id
            )
            if row is not None:
                row.messages.append({"role": "event", **payload})
                await session.commit()

    async def send_sms(body: str) -> str:
        # The one place the SMS tool touches a database — the engine holds no
        # session of its own, per its infrastructure-free contract. Always
        # built, even when the agent's toggle is off: build_context is what
        # decides whether the model ever sees the tool at all.
        if client is None or not client.phone:
            return "Cannot send SMS: no phone number is known for this caller."
        async with SessionMaker.get_session(org_uuid)() as session:
            try:
                await MessagingService(session, org_uuid).send_sms(
                    SSmsSend(
                        to=client.phone,
                        body=body,
                        messaging_id=agent_messaging_id,
                    ),
                    call_id=call_row.id,
                )
            except SendError as exc:
                return f"SMS failed to send: {exc}"
        return f"SMS sent to {client.phone}."

    call_session = CallSession(
        agent=agent_config,
        call=context,
        transport=transport,
        hooks=SessionHooks(
            on_started=on_started,
            on_finished=on_finished,
            on_language_switch=on_language_switch,
        ),
        send_sms=send_sms,
    )

    async def keep_live() -> None:
        # The liveness lock is what lets the sweep tell "long call" from
        # "dead process" within a TTL instead of a max-duration timeout. No
        # DB traffic: one TTL'd redis SET per refresh period.
        while True:
            await registry.mark_live(attempt_uuid)
            await asyncio.sleep(registry.LIVE_REFRESH_SECONDS)

    active_sessions[attempt_uuid] = call_session
    liveness = asyncio.create_task(keep_live())
    try:
        await call_session.run()
    except Exception as exc:  # noqa: BLE001 - a failed call is data, not a crash
        logger.exception(f"attempt {attempt_uuid}: session failed")
        await _set_status(
            org_uuid,
            attempt_id,
            CallStatusEnum.failed,
            only_from=(CallStatusEnum.dialing, CallStatusEnum.in_progress),
            extra={"error": str(exc)[:2000]},
        )
    else:
        await _set_status(
            org_uuid,
            attempt_id,
            CallStatusEnum.completed,
            only_from=(CallStatusEnum.dialing, CallStatusEnum.in_progress),
        )
    finally:
        liveness.cancel()
        await registry.clear_live(attempt_uuid)
        active_sessions.pop(attempt_uuid, None)
        # Bill the connected time, whatever way the call ended. Never lets a
        # billing hiccup mask the call's own outcome; the charge is idempotent
        # per attempt, so a retry elsewhere cannot double-bill.
        try:
            async with SessionMaker.get_session(org_uuid)() as session:
                await BillingService(session).charge_call(attempt_id)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"attempt {attempt_uuid}: call charge failed: {exc}")


async def drain(deadline_seconds: float = 300.0) -> None:
    """Let live calls finish, then hang up whatever remains.

    For the hooks process's shutdown path: a conversation is the one thing
    that must not be dropped mid-sentence because of a deploy.
    """
    import asyncio

    waited = 0.0
    while active_sessions and waited < deadline_seconds:
        await asyncio.sleep(1.0)
        waited += 1.0
    for session in list(active_sessions.values()):
        await session.hangup()
