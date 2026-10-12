"""Originating a call is more than inserting rows — this is where it lives.

The API cannot dial: a call is a long-lived stateful process that starts in
the taskiq worker and runs in the hooks service. What origination *can* do
synchronously is refuse early — an inactive agent, a missing trunk, a
non-callable client, a config that no longer validates — then persist the
call (the assignment) and its first attempt, commit, and enqueue the dial.
Commit before enqueue, deliberately: the task's claim reads the row, and the
sweep healing an invisible row costs a minute of latency. The rows, not the
queue, are the source of truth — a lost message is re-enqueued by the sweep;
a duplicate message loses the claim.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.engine.config import CallContext, resolve_profile
from src.common.enums.campaign import CallLifecycleEnum, ClientStatusEnum
from src.common.enums.engine import CallDirectionEnum, CallStatusEnum
from src.models.agent import VoiceAgent
from src.models.call import Call
from src.repositories.agent import VoiceAgentCRUD, build_agent_config
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.billing import OrganizationBalanceCRUD
from src.repositories.client import ClientCRUD
from src.schemas.admin import SCallCreate
from src.schemas.engine import CustomerProfile
from src.utils.phone import normalize_phone


#: Manual calls that may be open (queued, dialing or talking) at once per
#: organization; campaigns have their own pacing, API callers did not.
MAX_OPEN_MANUAL_CALLS = 50


class OriginateError(ValueError):
    """The call cannot even be queued; the message says why."""


class CallNotFound(LookupError):
    """The call id resolves to no row in this organization."""


class CallNotCancelable(ValueError):
    """The call's leg is already dialing, or the call is over."""


class CallService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def originate(self, data: SCallCreate) -> Call:
        """Queue a manual outbound call, refusing everything refusable up front.

        Validation runs the real path — rows → ``VoiceAgentConfig`` →
        ``resolve_profile`` — so a call that queues is a call the worker can
        build. The client is upserted by phone, same as a campaign upload.

        Args:
            data: The origination request.

        Returns:
            The created call row, first attempt queued.

        Raises:
            OriginateError: If the agent is missing, inactive, has no trunk,
                the client opted out, or the configuration does not validate.
        """
        agent = await VoiceAgentCRUD(self.session).get_one_or_none(
            VoiceAgent.id == data.agent_id
        )
        if agent is None:
            raise OriginateError(f"agent {data.agent_id} not found")
        if not agent.is_active:
            raise OriginateError(f"agent {data.agent_id} is not active")
        if agent.telephony is None:
            raise OriginateError(f"agent {data.agent_id} has no telephony binding")
        if not agent.telephony.is_active:
            raise OriginateError(f"telephony {agent.telephony_id} is not active")

        if not await OrganizationBalanceCRUD(self.session).has_funds("calls"):
            raise OriginateError("insufficient call balance")
        open_manual = await self.session.scalar(
            select(func.count(Call.id)).where(
                Call.campaign_id.is_(None),
                Call.status == CallLifecycleEnum.calling,
            )
        )
        if (open_manual or 0) >= MAX_OPEN_MANUAL_CALLS:
            raise OriginateError(
                f"too many manual calls in progress (limit {MAX_OPEN_MANUAL_CALLS})"
            )

        try:
            phone = normalize_phone(data.to_number)
        except ValueError as exc:
            raise OriginateError(str(exc)) from exc

        try:
            config = build_agent_config(agent)
            context = CallContext(
                call_id="originate",
                org_uuid="originate",
                direction=CallDirectionEnum.outbound,
                language=data.language,
                customer=CustomerProfile(name=data.name or ""),
                overrides=data.overrides,
            )
            profile = resolve_profile(config, context)
        except ValueError as exc:
            raise OriginateError(
                f"agent {data.agent_id} configuration is invalid: {exc}"
            ) from exc

        client = await ClientCRUD(self.session).upsert_by_phone(phone, data.name)
        if client.status != ClientStatusEnum.active:
            raise OriginateError(f"client {phone} is not callable ({client.status})")

        call = await CallCRUD(self.session).create(
            {
                "client_id": client.id,
                "agent_id": agent.id,
                "direction": CallDirectionEnum.outbound,
                "status": CallLifecycleEnum.calling,
                "from_number": data.from_number or agent.telephony.caller_id,
                "language": profile.language,
                "attributes": data.attributes,
                "bonuses": data.bonuses,
                "player_id": data.player_id,
                "vip_status": data.vip_status,
                "last_deposit": data.last_deposit,
                "last_active": data.last_active,
                "country": data.country,
                "timezone": data.timezone,
                "overrides": data.overrides.model_dump(exclude_unset=True)
                if data.overrides
                else None,
                "attempts_made": 1,
            }
        )
        attempt = await CallAttemptCRUD(self.session).create(
            {
                "call_id": call.id,
                "seq": 1,
                "status": CallStatusEnum.queued,
                "language": profile.language,
                "profile_summary": profile.summary(),
            }
        )

        # Committed before the enqueue — see the module docstring. The commit
        # dependency's own commit afterwards is a harmless no-op.
        await self.session.commit()
        from src.application.worker.tasks import enqueue_dial

        await enqueue_dial(org_uuid=self.session.org_uuid, attempt_id=attempt.id)
        # The in-memory collection predates the attempt row; load it properly
        # so the response carries the attempt without a sync lazy-load. `client`
        # is "lazy=joined" but that only fires on a SELECT — this object came
        # from create()'s add()+flush(), so it needs an explicit refresh too.
        await self.session.refresh(call, ["attempts", "client"])
        return call

    async def cancel(self, call_id: int) -> Call:
        """Cancel a call that is not mid-conversation. See ``CallCRUD.cancel``.

        Raises:
            CallNotFound: If the call does not exist.
            CallNotCancelable: If its leg is already dialing, or it is over.
        """
        calls = CallCRUD(self.session)
        if not await calls.cancel(call_id):
            if not await calls.exists(Call.id == call_id):
                raise CallNotFound(call_id)
            raise CallNotCancelable(call_id)
        return await calls.get_one_or_none(Call.id == call_id)

    async def set_tags(self, call_id: int, tags: list[str]) -> Call:
        """Replace a call's tags wholesale. See ``CallCRUD.set_tags``.

        Raises:
            CallNotFound: If the call does not exist.
        """
        calls = CallCRUD(self.session)
        if not await calls.set_tags(call_id, tags):
            raise CallNotFound(call_id)
        return await calls.get_one_or_none(Call.id == call_id)
