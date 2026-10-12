"""The campaign dispatcher's moves: settle, promote, claim.

Everything here is a guarded UPDATE on rows whose state is the source of
truth — the same at-most-once posture as ``dial_call``'s claim. The cron task
in ``tasks.py`` runs these per organization every minute; scheduling is
therefore datetime columns plus this poll, never messages queued into the
future (a queued future task cannot be paused, re-windowed, or audited; a row
can).

Settlement is deliberately the *only* writer of a call's lifecycle status
after dispatch: the runner, the sweep and the status webhook write attempt
rows, and this module folds the latest attempt's terminal status back into
the parent — one writer, no races across processes.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums.campaign import (
    CallLifecycleEnum,
    CallOutcomeEnum,
    CampaignStatusEnum,
    ClientStatusEnum,
)
from src.common.enums.engine import CallStatusEnum
from src.models.call import Call, CallAttempt
from src.models.campaign import Campaign
from src.models.client import Client
from src.models.messaging import Message
from src.repositories.call import SMS_SENT_STATUSES, CallAttemptCRUD
from src.repositories.campaign import campaign_hours, campaign_retry
from src.schemas.campaign import RetryPolicy
from src.utils.timezone import country_to_timezone

TERMINAL_ATTEMPT_STATUSES = frozenset(
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

#: Manual calls have no campaign and therefore no retry policy: one attempt.
_SINGLE_ATTEMPT = RetryPolicy(max_attempts=1)

#: An attempt this long past ``ended_at`` with no outcome means analysis keeps
#: failing; the call settles without one rather than waiting forever.
ANALYSIS_GIVE_UP = timedelta(minutes=15)

#: VOAD-33: calling-hours windows are now per-call (the client's country
#: decides the timezone), so a due row's eligibility can no longer be pushed
#: into the SQL ``LIMIT`` — a batch must be pulled and filtered in Python
#: before the budget is applied. This multiplier (capped) sizes that batch:
#: generous enough that a campaign spanning several timezones still fills its
#: budget from whichever countries are currently in-window, small enough that
#: one dispatcher tick never locks an unbounded number of rows.
_CLAIM_LOOKAHEAD_MULTIPLIER = 5
_CLAIM_LOOKAHEAD_CAP = 500


async def pending_analyses(session: AsyncSession) -> list[int]:
    """Completed attempts with a conversation and no outcome — analysis due.

    Re-selected every tick until the outcome lands: the analyze task rechecks
    the row before calling the LLM, so a repeat enqueue is the retry
    mechanism, not a bug. Attempts past :data:`ANALYSIS_GIVE_UP` are excluded;
    settle folds those without an outcome.
    """
    rows = await session.execute(
        select(CallAttempt.id).where(
            CallAttempt.status == CallStatusEnum.completed,
            CallAttempt.outcome.is_(None),
            func.jsonb_array_length(CallAttempt.messages) > 0,
            CallAttempt.ended_at.is_not(None),
            CallAttempt.ended_at > datetime.now() - ANALYSIS_GIVE_UP,
        )
    )
    return list(rows.scalars().all())


async def _block_client(session: AsyncSession, call: Call) -> None:
    """A do-not-call outcome: flag the client, cancel their pending calls —
    every campaign, not just this one."""
    if call.client_id is None:
        return
    await session.execute(
        update(Client)
        .where(Client.id == call.client_id, Client.status == ClientStatusEnum.active)
        .values(status=ClientStatusEnum.do_not_call)
    )
    await session.execute(
        update(Call)
        .where(
            Call.client_id == call.client_id, Call.status == CallLifecycleEnum.pending
        )
        .values(status=CallLifecycleEnum.canceled)
    )


async def _sms_sent_at(
    session: AsyncSession, calls: Collection[Call]
) -> dict[int, datetime]:
    """``call id -> latest created_at`` of a sent/delivered SMS, one query for
    the whole settle batch (only calls whose latest attempt completed)."""
    ids = [
        c.id
        for c in calls
        if c.attempts and c.attempts[-1].status == CallStatusEnum.completed
    ]
    if not ids:
        return {}
    rows = await session.execute(
        select(Message.call_id, func.max(Message.created_at))
        .where(Message.call_id.in_(ids), Message.status.in_(SMS_SENT_STATUSES))
        .group_by(Message.call_id)
    )
    return {call_id: at for call_id, at in rows.all()}


async def settle_calls(
    session: AsyncSession, call_ids: Collection[int] | None = None
) -> int:
    """Fold terminal attempts back into their parent calls.

    A ``calling`` parent whose latest attempt ended becomes: ``completed``
    (conversation happened), ``canceled`` (someone decided), ``pending`` with
    ``next_attempt_at`` (retry earned — policy delay, or the recall time the
    caller named), or ``exhausted`` (policy ran out). Attempts that still owe
    an analysis result are left alone until it lands or gives up; outcomes
    drive the side effects (do-not-call blocks the client everywhere).

    Args:
        session: Organization session.
        call_ids: Settle only these calls (used right after a terminal status
            webhook so the parent does not lag a whole dispatcher tick behind
            its attempt); ``None`` settles every ``calling`` call.

    Returns:
        How many calls were settled.
    """
    now = datetime.now()
    query = select(Call).where(Call.status == CallLifecycleEnum.calling)
    if call_ids is not None:
        query = query.where(Call.id.in_(list(call_ids)))
    calls = (
        (await session.execute(query))
        .unique()
        .scalars()
        .all()
    )
    sms_at = await _sms_sent_at(session, calls)
    settled = 0
    for call in calls:
        last = call.attempts[-1] if call.attempts else None
        if last is None or last.status not in TERMINAL_ATTEMPT_STATUSES:
            continue

        policy = campaign_retry(call.campaign) if call.campaign else _SINGLE_ATTEMPT
        next_at: datetime | None = None
        is_callback = False
        outcome = last.outcome
        selected_offer = last.selected_offer
        sentiment = last.sentiment
        reason_category = last.reason_category

        if last.status == CallStatusEnum.completed:
            awaiting_analysis = outcome is None and len(last.messages) > 0
            if awaiting_analysis:
                if last.ended_at is None or last.ended_at > now - ANALYSIS_GIVE_UP:
                    continue
                logger.warning(
                    f"call {call.id}: attempt {last.id} has no outcome "
                    f"{ANALYSIS_GIVE_UP} after ending; settling without one"
                )
            status = CallLifecycleEnum.completed
            # VOAD-80: the agent's SMS *is* the result of the call. It
            # overwrites the analysis outcome (and so cancels a call_later
            # callback) — except do_not_call, which keeps the client blocked.
            sms = sms_at.get(call.id)
            if (
                sms is not None
                and sms >= last.created_at
                and outcome != CallOutcomeEnum.do_not_call
            ):
                outcome = CallOutcomeEnum.sms_sent
                await session.execute(
                    update(CallAttempt)
                    .where(
                        CallAttempt.id == last.id,
                        or_(
                            CallAttempt.outcome.is_(None),
                            CallAttempt.outcome != CallOutcomeEnum.do_not_call,
                        ),
                    )
                    .values(outcome=outcome)
                )
            if outcome == CallOutcomeEnum.do_not_call:
                await _block_client(session, call)
            elif (
                outcome == CallOutcomeEnum.call_later
                and call.campaign is not None
                and call.attempts_made - call.attempt_base < policy.max_attempts
            ):
                status = CallLifecycleEnum.pending
                # The claim cleared next_attempt_at, so a value here is the
                # recall time analysis extracted; without one, the caller
                # named no time and the retry policy paces the callback.
                if call.next_attempt_at is not None and call.next_attempt_at > now:
                    next_at = call.next_attempt_at
                    is_callback = True
                else:
                    next_at = now + timedelta(seconds=policy.no_answer_delay_seconds)
        elif last.status == CallStatusEnum.canceled:
            status = CallLifecycleEnum.canceled
        else:  # busy / no_answer / rejected / invalid_number / failed
            ctx = (
                f"call {call.id}: attempt {last.id} provider_ref={last.provider_ref} "
                f"provider_status={last.provider_status} error={last.error}"
            )
            effective = last.status
            if last.status == CallStatusEnum.failed:
                if (last.error or "").strip():
                    # A carrier or service failure hits one call, not the whole
                    # campaign: log it and let the retry policy pace the next try.
                    logger.error(f"{ctx}: failed with system/service error")
                else:
                    # Nothing says the platform broke: the callee just never
                    # picked up in a way the provider could describe.
                    logger.warning(f"{ctx}: failed without an error, treating as no_answer")
                    effective = CallStatusEnum.no_answer
            else:
                logger.info(f"{ctx}: ended as {last.status}")

            new_outcome: CallOutcomeEnum | None = None
            if effective in (
                CallStatusEnum.busy,
                CallStatusEnum.no_answer,
                CallStatusEnum.rejected,
            ):
                new_outcome = CallOutcomeEnum.no_answer
            elif effective == CallStatusEnum.invalid_number:
                new_outcome = CallOutcomeEnum.wrong_number
            if new_outcome is not None:
                outcome = new_outcome
                if last.outcome is None:
                    await session.execute(
                        update(CallAttempt)
                        .where(CallAttempt.id == last.id, CallAttempt.outcome.is_(None))
                        .values(outcome=new_outcome)
                    )
            # invalid_number has no delay: the call closes without a retry.
            delay = policy.delay_for(effective)
            if (
                delay is None
                or call.attempts_made - call.attempt_base >= policy.max_attempts
            ):
                status = CallLifecycleEnum.exhausted
            else:
                status = CallLifecycleEnum.pending
                next_at = now + timedelta(seconds=delay)

        result = await session.execute(
            update(Call)
            .where(Call.id == call.id, Call.status == CallLifecycleEnum.calling)
            .values(
                status=status,
                next_attempt_at=next_at,
                is_callback=is_callback,
                outcome=outcome,
                selected_offer=selected_offer,
                sentiment=sentiment,
                reason_category=reason_category,
            )
        )
        settled += result.rowcount
    return settled


async def promote_campaigns(session: AsyncSession) -> None:
    """Apply the time-based campaign transitions.

    ``scheduled → running`` once ``starts_at`` arrives; ``running →
    completed`` once ``ends_at`` passes (remaining pending calls canceled) or
    once every call has reached a terminal state.
    """
    now = datetime.now()
    await session.execute(
        update(Campaign)
        .where(
            Campaign.status == CampaignStatusEnum.scheduled,
            Campaign.starts_at.is_not(None),
            Campaign.starts_at <= now,
        )
        .values(status=CampaignStatusEnum.running)
    )

    ended = (
        (
            await session.execute(
                select(Campaign.id).where(
                    Campaign.status == CampaignStatusEnum.running,
                    Campaign.ends_at.is_not(None),
                    Campaign.ends_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    if ended:
        await session.execute(
            update(Call)
            .where(
                Call.campaign_id.in_(ended), Call.status == CallLifecycleEnum.pending
            )
            .values(status=CallLifecycleEnum.canceled)
        )
        await session.execute(
            update(Campaign)
            .where(Campaign.id.in_(ended))
            .values(status=CampaignStatusEnum.completed)
        )

    # Out of work: has calls, none of them still pending or in flight.
    has_calls = exists().where(Call.campaign_id == Campaign.id)
    has_open = exists().where(
        Call.campaign_id == Campaign.id,
        Call.status.in_((CallLifecycleEnum.pending, CallLifecycleEnum.calling)),
    )
    await session.execute(
        update(Campaign)
        .where(Campaign.status == CampaignStatusEnum.running, has_calls, ~has_open)
        .values(status=CampaignStatusEnum.completed)
    )


async def claim_due_calls(session: AsyncSession, budget: int) -> list[int]:
    """Claim due calls of running campaigns and spawn their attempts.

    ``budget`` is the number of dials this tick may start (capacity and rate
    already accounted for by the caller). Calls whose client is no longer
    ``active`` are moved to ``blocked`` instead of dialed — a late opt-out
    wins over an uploaded row.

    A due call's window is evaluated on the timezone derived from its
    client's country (VOAD-33), not the campaign's configured ``timezone`` —
    that stays the fallback for a client with no resolvable country, which is
    also the entire behavior for a campaign whose clients carry no country
    data at all. Among the calls currently in window, ones inside a
    configured priority interval are claimed first, ahead of same-tick calls
    that are only inside the general window; within each tier, due order
    (``next_attempt_at`` then ``id``) is preserved.

    Returns:
        Ids of the created (queued) attempts, for the caller to kick.
    """
    attempt_ids: list[int] = []
    campaigns = (
        (
            await session.execute(
                select(Campaign).where(Campaign.status == CampaignStatusEnum.running)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    for campaign in campaigns:
        if budget <= 0:
            break
        hours = campaign_hours(campaign)
        now = datetime.now()

        await session.execute(
            update(Call)
            .where(
                Call.campaign_id == campaign.id,
                Call.status == CallLifecycleEnum.pending,
                Call.client_id.in_(
                    select(Client.id).where(Client.status != ClientStatusEnum.active)
                ),
            )
            .values(status=CallLifecycleEnum.blocked)
        )

        lookahead = min(budget * _CLAIM_LOOKAHEAD_MULTIPLIER, _CLAIM_LOOKAHEAD_CAP)
        due_ids = (
            (
                await session.execute(
                    select(Call.id)
                    .where(
                        Call.campaign_id == campaign.id,
                        Call.status == CallLifecycleEnum.pending,
                        (Call.next_attempt_at.is_(None))
                        | (Call.next_attempt_at <= now),
                    )
                    .order_by(Call.next_attempt_at.asc().nulls_first(), Call.id)
                    .limit(lookahead)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not due_ids:
            continue

        countries = dict(
            (
                await session.execute(
                    select(Call.id, Client.country)
                    .join(Client, Call.client_id == Client.id, isouter=True)
                    .where(Call.id.in_(due_ids))
                )
            ).all()
        )

        # In due order (already SQL-sorted): split into priority vs. plain
        # open calls, on each call's own client-country timezone (or the
        # campaign's own, unresolved/unknown country alike).
        priority_ids: list[int] = []
        normal_ids: list[int] = []
        for call_id in due_ids:
            zone = country_to_timezone(countries.get(call_id)) or hours.timezone
            if not hours.is_open(now, timezone=zone):
                continue
            if hours.is_priority(now, timezone=zone):
                priority_ids.append(call_id)
            else:
                normal_ids.append(call_id)

        selected_ids = (priority_ids + normal_ids)[:budget]
        if not selected_ids:
            continue

        claimed = (
            await session.execute(
                update(Call)
                .where(Call.id.in_(selected_ids))
                .values(
                    status=CallLifecycleEnum.calling,
                    attempts_made=Call.attempts_made + 1,
                    # Cleared so that at settle time a non-NULL value can only
                    # be the recall time this attempt's analysis wrote.
                    next_attempt_at=None,
                    is_callback=False,
                )
                .returning(Call.id, Call.attempts_made, Call.language)
            )
        ).all()

        attempts = CallAttemptCRUD(session)
        for row in claimed:
            attempt = await attempts.create(
                {
                    "call_id": row.id,
                    "seq": row.attempts_made,
                    "status": CallStatusEnum.queued,
                    "language": row.language,
                }
            )
            attempt_ids.append(attempt.id)
        budget -= len(claimed)
    return attempt_ids
