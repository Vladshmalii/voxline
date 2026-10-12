"""The dialing side of the worker, as taskiq tasks — no long-lived loop.

Everything outbound is a small, idempotent unit of work:

* ``dial_call`` — dials one queued *attempt*. Its claim is one guarded UPDATE
  (``queued → dialing`` on that exact row), so a duplicate delivery, a
  concurrent instance, or a race with the API's cancel all resolve to
  "exactly one dialer, or none" without coordination.
* ``dispatch_campaigns`` — the campaign tick: settles calls whose attempt
  ended, applies time-based campaign transitions, claims due calls within
  capacity and rate, spawns their attempts and enqueues the dials. See
  ``dispatch.py`` for the moves themselves.
* ``sweep_calls`` — repairs whatever crashes strand: re-enqueues queued
  attempts whose dial message got lost, fails ``dialing`` attempts whose
  media socket never came, and fails ``in_progress`` attempts whose runner
  stopped refreshing its liveness lock.

Delivery count doesn't matter by design, not because the broker guarantees
exactly one: the broker (Redis Streams, see ``broker.py``) redelivers an
unacked message, and a duplicate delivery finds its row already claimed by
``dial_call``'s guarded UPDATE and no-ops — it never rings a customer's phone
twice. A message the broker loses outright (nobody ever delivered it) is
healed separately, by the sweep re-enqueueing it — a queued attempt is never
stranded for more than one sweep interval.

Deployment: ``taskiq worker src.application.worker.tasks:broker`` and
``taskiq scheduler src.application.worker.tasks:scheduler`` (see
``scripts/worker.sh`` / ``scripts/scheduler.sh``). Both run any number of
instances safely; the pipelines themselves live in the hooks service.
"""

from __future__ import annotations

import asyncio

# Settings first: importing it runs the core Config.init, which the ORM
# base below (src.core.db.session, src.models.*) requires. Keeps this module
# a safe import root (taskiq CLI, tests) regardless of who imports it first.
from src.settings import SETTINGS  # isort: skip

from loguru import logger
from sqlalchemy import func, select, text, update
from taskiq import TaskiqEvents, TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from src.application.engine.config import CallContext, resolve_profile
from src.application.services import analysis
from src.application.worker import dispatch, registry
from src.application.worker.broker import make_broker
from src.common.enums.campaign import CallLifecycleEnum
from src.common.enums.engine import CallStatusEnum
from src.core.control import directory
from src.core.db.session import SessionMaker
from src.core.redis import RedisBase
from src.integrations.telephony import build_telephony
from src.models.agent import VoiceAgent
from src.models.call import Call, CallAttempt
from src.models.provider import Model
from src.repositories.agent import (
    VoiceAgentCRUD,
    build_agent_config,
    build_analysis_config,
)
from src.repositories.billing import OrganizationBalanceCRUD
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.provider import ModelCRUD
from src.repositories.telephony import TelephonyCRUD

broker = make_broker()

#: Held for the length of one dispatcher tick (TTL just under the cron period,
#: so a crashed tick cannot block the next one for long).
_DISPATCH_LOCK = "call:dispatch:lock"
_DISPATCH_LOCK_TTL = 55
#: Upper bound for one analysis LLM call; the lock lapses on its own after a crash.
_ANALYZE_LOCK_TTL = 300


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _worker_startup(_state) -> None:
    from src.infrastructure import startup

    await startup(SETTINGS)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _worker_shutdown(_state) -> None:
    from src.infrastructure import shutdown

    await shutdown(SETTINGS)


_producer_started = asyncio.Lock()


async def enqueue_dial(org_uuid: str, attempt_id: int) -> None:
    """Enqueue a dial from a producer process (the API).

    Call it only after the rows are committed — the task may run before an
    uncommitted row is visible and would (correctly) find nothing to claim;
    the sweep would then heal it a minute later, which is a worse experience
    than just committing first.
    """
    async with _producer_started:
        if not broker.is_worker_process and not getattr(
            broker, "_voxline_started", False
        ):
            await broker.startup()
            broker._voxline_started = True
    await dial_call.kiq(org_uuid=org_uuid, attempt_id=attempt_id)


@broker.task
async def dial_call(org_uuid: str, attempt_id: int) -> None:
    """Claim one queued attempt and originate it. Idempotent; safe to duplicate.

    Args:
        org_uuid: Organization whose database holds the attempt.
        attempt_id: The attempt row to dial.
    """
    settings = SETTINGS.call_worker
    if settings is None:
        raise RuntimeError("CALL_WORKER__ settings are required for the worker process")

    if await registry.in_flight() >= settings.max_concurrent_calls:
        # Leave the row queued; the sweep re-enqueues once capacity frees up.
        logger.info(
            f"attempt {attempt_id} in org {org_uuid}: at capacity, staying queued"
        )
        return

    # The claim: exactly one delivery wins this UPDATE; a duplicate task, a
    # second worker, or a cancel that got there first all see rowcount 0.
    async with SessionMaker.get_session(org_uuid)() as session:
        stmt = (
            update(CallAttempt)
            .where(
                CallAttempt.id == attempt_id,
                CallAttempt.status == CallStatusEnum.queued,
            )
            .values(status=CallStatusEnum.dialing)
            .returning(CallAttempt.uuid, CallAttempt.call_id)
        )
        claimed = (await session.execute(stmt)).mappings().one_or_none()
        await session.commit()
    if claimed is None:
        return

    attempt_uuid = str(claimed["uuid"])

    async def fail(reason: str) -> None:
        await registry.discard(attempt_uuid)
        async with SessionMaker.get_session(org_uuid)() as session:
            await CallAttemptCRUD(session).update(
                CallAttempt.id == attempt_id,
                data={"status": CallStatusEnum.failed, "error": reason[:2000]},
            )
            await session.commit()
            # Settle the parent now rather than a tick later (best effort).
            try:
                await dispatch.settle_calls(session, call_ids=[claimed["call_id"]])
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - the tick will settle it
                logger.warning(
                    f"attempt {attempt_uuid}: immediate settle failed: {exc}"
                )
        logger.warning(f"attempt {attempt_uuid}: dial failed: {reason}")

    try:
        async with SessionMaker.get_session(org_uuid)() as session:
            call_row = await CallCRUD(session).get_one_or_none(
                Call.id == claimed["call_id"]
            )
            if call_row is None or call_row.client is None:
                await fail("call or its client disappeared after queueing")
                return
            agent = await VoiceAgentCRUD(session).get_one_or_none(
                VoiceAgent.id == call_row.agent_id
            )
            if (
                agent is None
                or agent.telephony is None
                or not agent.telephony.is_active
            ):
                await fail("agent lost its telephony binding after queueing")
                return
            telephony_config = TelephonyCRUD.build_config(agent.telephony)
            media_base = registry.media_base(
                agent.telephony.options, settings.media_url
            )
            to_number = call_row.client.phone
            from_number = call_row.from_number or agent.telephony.caller_id

        # Derived in one place: the hooks service re-derives the status URL to
        # verify a carrier's webhook signature against the exact string we
        # handed out (see registry.call_urls).
        media_url, status_url = registry.call_urls(
            SETTINGS.secret_key, media_base, attempt_uuid
        )

        # Registered before the dial: the socket can beat the dial response.
        # The registry's call_id is the *attempt* id — the leg is the unit the
        # media socket and webhooks address.
        await registry.register(
            attempt_uuid,
            org_uuid=org_uuid,
            call_id=attempt_id,
            dial_ttl=settings.dial_timeout_seconds + 5,
            route_ttl=settings.max_call_seconds,
        )

        # The early check above is a cheap shortcut; this one is the real
        # gate. The slot was taken by ``register``, so concurrent dials each
        # see the others and the platform cap holds. A loser goes back to
        # ``queued`` for the sweep to retry once capacity frees up.
        if await registry.in_flight() > settings.max_concurrent_calls:
            await registry.discard(attempt_uuid)
            async with SessionMaker.get_session(org_uuid)() as session:
                await CallAttemptCRUD(session).update(
                    CallAttempt.id == attempt_id,
                    CallAttempt.status == CallStatusEnum.dialing,
                    data={"status": CallStatusEnum.queued},
                )
                await session.commit()
            logger.info(f"attempt {attempt_uuid}: lost the capacity race, requeued")
            return

        adapter = build_telephony(telephony_config, call_id=attempt_uuid)
        provider_ref = await adapter.dial(
            to=to_number,
            media_url=media_url,
            caller_id=from_number,
            status_url=status_url,
        )
    except Exception as exc:  # noqa: BLE001 - a failed dial is data, not a crash
        await fail(str(exc))
        return

    # The phone is ringing now. Recording the reference is bookkeeping: if it
    # fails the call must NOT be marked failed (the retry policy would ring the
    # customer a second time while the first call is still connecting).
    try:
        async with SessionMaker.get_session(org_uuid)() as session:
            await CallAttemptCRUD(session).update(
                CallAttempt.id == attempt_id, data={"provider_ref": provider_ref}
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"attempt {attempt_uuid}: dialed (ref={provider_ref}) but saving the "
            f"reference failed: {exc}"
        )
    logger.info(f"attempt {attempt_uuid}: dialed {to_number} (ref={provider_ref})")


@broker.task
async def analyze_attempt(org_uuid: str, attempt_id: int) -> None:
    """Summarize one finished attempt and record its business outcome.

    Enqueued by the dispatcher tick for completed attempts with a conversation
    and no outcome — repeatedly, until the outcome lands, which makes repeat
    delivery the retry mechanism: the row is rechecked before the LLM is
    called and the write is guarded on ``outcome`` still being NULL.
    """
    async with SessionMaker.get_session(org_uuid)() as session:
        attempt = await CallAttemptCRUD(session).get_one_or_none(
            CallAttempt.id == attempt_id
        )
        if (
            attempt is None
            or attempt.status != CallStatusEnum.completed
            or attempt.outcome is not None
            or not attempt.messages
        ):
            return
        call_row = attempt.call
        agent = await VoiceAgentCRUD(session).get_one_or_none(
            VoiceAgent.id == call_row.agent_id
        )
        if agent is None:
            logger.warning(f"attempt {attempt_id}: agent is gone, cannot analyze")
            return
        try:
            profile = resolve_profile(
                build_agent_config(agent),
                CallContext(
                    call_id=f"analysis-{attempt_id}",
                    org_uuid=org_uuid,
                    language=attempt.language or call_row.language,
                ),
            )
        except ValueError as exc:
            logger.warning(
                f"attempt {attempt_id}: agent config invalid, cannot analyze: {exc}"
            )
            return
        transcript = analysis.render_transcript(
            attempt.messages,
            scaffolding=frozenset({profile.prompts.greeting_kickoff.strip()}),
        )
        call_id, language = attempt.call_id, profile.language
        offers = [analysis.offer_label(offer) for offer in call_row.bonuses]
        # The organization's analysis model, when an admin flagged one;
        # otherwise the LLM this call itself ran on.
        analysis_model = await ModelCRUD(session).get_one_or_none(
            Model.is_analysis.is_(True), Model.is_active.is_(True)
        )
        ttt = (
            build_analysis_config(analysis_model)
            if analysis_model is not None
            else profile.ttt
        )

    if not transcript:
        return  # nothing was really said; settle folds it without an outcome

    # Every tick re-enqueues an attempt until its outcome lands, so a slow LLM
    # or a backed-up queue would stack paid duplicates. One run at a time.
    redis = await RedisBase.get_client()
    lock = f"call:analyze:{org_uuid}:{attempt_id}"
    if not await redis.set(lock, "1", nx=True, ex=_ANALYZE_LOCK_TTL):
        return
    try:
        result = await analysis.analyze_transcript(
            ttt, transcript, language=language, offers=offers
        )
    except analysis.AnalysisError as exc:
        logger.warning(
            f"attempt {attempt_id}: analysis failed, next tick retries: {exc}"
        )
        await redis.delete(lock)
        return
    await redis.delete(lock)

    async with SessionMaker.get_session(org_uuid)() as session:
        updated = await CallAttemptCRUD(session).update(
            CallAttempt.id == attempt_id,
            CallAttempt.outcome.is_(None),
            data={
                "summary": result.summary,
                "outcome": result.outcome,
                "selected_offer": result.selected_offer,
                "sentiment": result.sentiment,
                "reason_category": result.reason_category,
            },
        )
        if updated and result.recall_at is not None:
            # The caller named a time; hand it to settle through the call's
            # scheduling column (the claim cleared it, so present == fresh).
            await session.execute(
                update(Call)
                .where(Call.id == call_id, Call.status == CallLifecycleEnum.calling)
                .values(next_attempt_at=result.recall_at)
            )
        await session.commit()
    if updated:
        logger.info(f"attempt {attempt_id}: analyzed, outcome={result.outcome}")


@broker.task(schedule=[{"cron": "* * * * *"}])
async def dispatch_campaigns() -> None:
    """The campaign tick: settle, promote, claim, dial. Runs each minute.

    The claim budget is capacity minus in-flight, capped by the per-minute
    dial rate — the tick itself is the pacer, which is why calls are claimed
    from datetime columns here rather than pre-scheduled as future tasks.
    """
    settings = SETTINGS.call_worker
    if settings is None:
        return

    try:
        organizations = await directory.organizations_list()
    except Exception as exc:  # noqa: BLE001 - tick again next minute
        logger.warning(f"dispatch: organization roster unavailable: {exc}")
        return

    # One tick at a time: a slow tick must not be overlapped by the next
    # minute's, or both would spend the same capacity.
    redis = await RedisBase.get_client()
    if not await redis.set(_DISPATCH_LOCK, "1", nx=True, ex=_DISPATCH_LOCK_TTL):
        logger.warning("dispatch: previous tick still running, skipping")
        return

    try:
        # Platform-wide capacity, spent across organizations: each org's claim
        # reduces what is left for the next, instead of every org seeing the
        # same untouched number.
        remaining = max(
            0, settings.max_concurrent_calls - await registry.in_flight()
        )
        remaining = min(remaining, settings.max_dials_per_minute)
        for org in organizations:
            org_uuid = org["uuid"]
            try:
                async with SessionMaker.get_session(org_uuid)() as session:
                    analysis_ids = await dispatch.pending_analyses(session)
                    settled = await dispatch.settle_calls(session)
                    await dispatch.promote_campaigns(session)
                    # No funds, no new dials for this organization (calls
                    # already in flight finish and are billed).
                    funded = await OrganizationBalanceCRUD(session).has_funds("calls")
                    attempt_ids = await dispatch.claim_due_calls(
                        session, remaining if funded else 0
                    )
                    await session.commit()
                remaining -= len(attempt_ids)
                for attempt_id in analysis_ids:
                    await analyze_attempt.kiq(org_uuid=org_uuid, attempt_id=attempt_id)
                for attempt_id in attempt_ids:
                    await dial_call.kiq(org_uuid=org_uuid, attempt_id=attempt_id)
                if settled or attempt_ids or analysis_ids:
                    logger.info(
                        f"dispatch: org {org_uuid}: settled {settled}, analyzing "
                        f"{len(analysis_ids)}, dialing {len(attempt_ids)} attempts"
                    )
            except Exception as exc:  # noqa: BLE001 - one org must not stop the rest
                logger.warning(f"dispatch: org {org_uuid} failed: {exc}")
            finally:
                # Hand the idle connection back: a minute-by-minute visit to
                # every org must not pin a connection per org per process.
                await SessionMaker.release_idle(org_uuid)
    finally:
        await redis.delete(_DISPATCH_LOCK)


@broker.task(schedule=[{"cron": "* * * * *"}])
async def sweep_calls() -> None:
    """Repair strandable attempt states across every organization. Runs each minute.

    Idempotent throughout — every action is a guarded UPDATE or a re-enqueue
    whose claim loses harmlessly — so overlapping sweeps from several
    schedulers cost queries, not correctness.
    """
    settings = SETTINGS.call_worker
    if settings is None:
        return

    try:
        organizations = await directory.organizations_list()
    except Exception as exc:  # noqa: BLE001 - sweep again next minute
        logger.warning(f"sweep: organization roster unavailable: {exc}")
        return

    for org in organizations:
        org_uuid = org["uuid"]
        try:
            await _sweep_org(
                org_uuid, settings.dial_timeout_seconds, settings.max_call_seconds
            )
        except Exception as exc:  # noqa: BLE001 - one org must not stop the rest
            logger.warning(f"sweep: org {org_uuid} failed: {exc}")
        finally:
            await SessionMaker.release_idle(org_uuid)


def func_now_minus(seconds: int):
    """``now() - interval``, computed on the database's clock, not ours."""
    return func.now() - text(f"INTERVAL '{seconds} seconds'")


async def _sweep_org(org_uuid: str, dial_timeout: int, max_call: int) -> None:
    async with SessionMaker.get_session(org_uuid)() as session:
        # Queued attempts whose dial message was lost (or deferred at
        # capacity): re-enqueue. The claim makes duplicates harmless.
        queued = (
            (
                await session.execute(
                    select(CallAttempt.id).where(
                        CallAttempt.status == CallStatusEnum.queued,
                        CallAttempt.updated_at < func_now_minus(30),
                    )
                )
            )
            .scalars()
            .all()
        )

        # Dialing attempts whose media socket never arrived.
        stranded = (
            (
                await session.execute(
                    update(CallAttempt)
                    .where(
                        CallAttempt.status == CallStatusEnum.dialing,
                        CallAttempt.updated_at < func_now_minus(dial_timeout * 2),
                    )
                    .values(
                        status=CallStatusEnum.failed,
                        error="media socket never arrived within the dial window",
                    )
                    .returning(CallAttempt.id)
                )
            )
            .scalars()
            .all()
        )

        # In-progress attempts: alive means a runner is refreshing the lock.
        in_progress = (
            (
                await session.execute(
                    select(CallAttempt.id, CallAttempt.uuid).where(
                        CallAttempt.status == CallStatusEnum.in_progress
                    )
                )
            )
            .mappings()
            .all()
        )
        dead: list[int] = []
        for row in in_progress:
            if not await registry.is_live(str(row["uuid"])):
                dead.append(row["id"])
        leaked: list[int] = []
        if dead:
            leaked += (
                (
                    await session.execute(
                        update(CallAttempt)
                        .where(
                            CallAttempt.id.in_(dead),
                            CallAttempt.status == CallStatusEnum.in_progress,
                        )
                        .values(
                            status=CallStatusEnum.failed,
                            error="call runner stopped responding",
                        )
                        .returning(CallAttempt.id)
                    )
                )
                .scalars()
                .all()
            )
        # Belt and braces: even a live-looking call cannot outrun max_call.
        leaked += (
            (
                await session.execute(
                    update(CallAttempt)
                    .where(
                        CallAttempt.status == CallStatusEnum.in_progress,
                        CallAttempt.updated_at < func_now_minus(max_call),
                    )
                    .values(
                        status=CallStatusEnum.failed,
                        error="call leaked past max duration",
                    )
                    .returning(CallAttempt.id)
                )
            )
            .scalars()
            .all()
        )
        await session.commit()

    for attempt_id in queued:
        await dial_call.kiq(org_uuid=org_uuid, attempt_id=attempt_id)
    if queued or stranded or leaked:
        logger.warning(
            f"sweep: org {org_uuid}: re-enqueued {len(queued)} queued {list(queued)}, "
            f"failed {len(stranded)} stranded dials {stranded}, "
            f"{len(leaked)} dead calls {leaked}"
        )


scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
