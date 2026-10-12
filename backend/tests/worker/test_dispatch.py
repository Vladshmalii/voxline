"""The dispatcher's moves: settle, promote, claim — all guarded row surgery."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import update

from src.application.worker.dispatch import (
    claim_due_calls,
    promote_campaigns,
    settle_calls,
)
from src.common.enums.campaign import (
    CallLifecycleEnum,
    CampaignStatusEnum,
    ClientStatusEnum,
)
from src.common.enums.engine import CallStatusEnum
from src.models.call import Call, CallAttempt
from src.models.campaign import Campaign
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.campaign import CampaignCRUD
from src.repositories.client import ClientCRUD
from tests.support import seed_stack


async def _campaign(session, agent_id: int, **extra) -> Campaign:
    return await CampaignCRUD(session).create(
        {
            "name": "welcome-back",
            "agent_id": agent_id,
            "status": CampaignStatusEnum.running,
            "call_script": "Offer {{ name }} the bonus.",
            **extra,
        }
    )


async def _call(session, agent_id: int, phone: str, campaign_id=None, **extra) -> Call:
    client = await ClientCRUD(session).upsert_by_phone(phone)
    return await CallCRUD(session).create(
        {
            "client_id": client.id,
            "campaign_id": campaign_id,
            "agent_id": agent_id,
            "status": CallLifecycleEnum.pending,
            **extra,
        }
    )


async def _with_attempt(session, call: Call, status: CallStatusEnum, **attempt_fields):
    """Move the call to ``calling`` with one attempt in ``status``; returns the
    attempt (the call's own collection is stale in-memory — don't touch it)."""
    call.status = CallLifecycleEnum.calling
    call.attempts_made += 1
    attempt = await CallAttemptCRUD(session).create(
        {
            "call_id": call.id,
            "seq": call.attempts_made,
            "status": status,
            **attempt_fields,
        }
    )
    await session.commit()
    return attempt


def _fresh(session, call_id: int):
    session.expire_all()
    return CallCRUD(session).get_one_or_none(Call.id == call_id)


async def test_settle_folds_the_attempt_into_the_call(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 2})

    talked = await _call(session, stack.agent.id, "+15551110001", campaign.id)
    await _with_attempt(session, talked, CallStatusEnum.completed)
    retryable = await _call(session, stack.agent.id, "+15551110002", campaign.id)
    await _with_attempt(session, retryable, CallStatusEnum.no_answer)
    still_live = await _call(session, stack.agent.id, "+15551110003", campaign.id)
    await _with_attempt(session, still_live, CallStatusEnum.in_progress)
    ids = {"talked": talked.id, "retryable": retryable.id, "live": still_live.id}

    settled = await settle_calls(session)
    await session.commit()
    assert settled == 2

    assert (await _fresh(session, ids["talked"])).status == CallLifecycleEnum.completed
    retry_row = await _fresh(session, ids["retryable"])
    assert retry_row.status == CallLifecycleEnum.pending  # earned another try
    assert retry_row.next_attempt_at > datetime.now()  # but not immediately
    assert (await _fresh(session, ids["live"])).status == CallLifecycleEnum.calling


async def test_settle_exhausts_when_policy_runs_out(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 1})

    out_of_tries = await _call(session, stack.agent.id, "+15551110004", campaign.id)
    await _with_attempt(session, out_of_tries, CallStatusEnum.busy)
    # Manual calls have no campaign, therefore no retries: one attempt, done.
    manual = await _call(session, stack.agent.id, "+15551110005", None)
    await _with_attempt(session, manual, CallStatusEnum.failed)
    ids = {"out": out_of_tries.id, "manual": manual.id}

    await settle_calls(session)
    await session.commit()

    assert (await _fresh(session, ids["out"])).status == CallLifecycleEnum.exhausted
    assert (await _fresh(session, ids["manual"])).status == CallLifecycleEnum.exhausted


async def test_failed_attempt_retries_without_halting_the_campaign(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 2})

    flaky = await _call(session, stack.agent.id, "+15551110007", campaign.id)
    await _with_attempt(session, flaky, CallStatusEnum.failed)
    ids = {"flaky": flaky.id, "campaign": campaign.id}

    await settle_calls(session)
    await session.commit()

    retry_row = await _fresh(session, ids["flaky"])
    assert retry_row.status == CallLifecycleEnum.pending  # earned another try
    assert retry_row.next_attempt_at > datetime.now()
    session.expire_all()
    still_running = await CampaignCRUD(session).get_one_or_none(
        Campaign.id == ids["campaign"]
    )
    assert still_running.status == CampaignStatusEnum.running


async def test_promote_moves_campaigns_on_the_clock(org_uuid, session):
    stack = await seed_stack(session)
    due = await _campaign(
        session,
        stack.agent.id,
        status=CampaignStatusEnum.scheduled,
        starts_at=datetime.now() - timedelta(minutes=1),
    )
    over = await _campaign(
        session, stack.agent.id, ends_at=datetime.now() - timedelta(minutes=1)
    )
    leftover = await _call(session, stack.agent.id, "+15551110006", over.id)
    ids = {"due": due.id, "over": over.id, "leftover": leftover.id}
    await session.commit()

    await promote_campaigns(session)
    await session.commit()
    session.expire_all()

    repo = CampaignCRUD(session)
    assert (
        await repo.get_one_or_none(Campaign.id == ids["due"])
    ).status == CampaignStatusEnum.running
    # Past its end: completed, and the never-dialed call is canceled, not left.
    assert (
        await repo.get_one_or_none(Campaign.id == ids["over"])
    ).status == CampaignStatusEnum.completed
    assert (await _fresh(session, ids["leftover"])).status == CallLifecycleEnum.canceled


async def test_promote_completes_a_campaign_out_of_work(org_uuid, session):
    stack = await seed_stack(session)
    done = await _campaign(session, stack.agent.id)
    call = await _call(session, stack.agent.id, "+15551110007", done.id)
    call.status = CallLifecycleEnum.completed
    # A running campaign with no calls yet is being set up, not finished.
    empty = await _campaign(session, stack.agent.id)
    ids = {"done": done.id, "empty": empty.id}
    await session.commit()

    await promote_campaigns(session)
    await session.commit()
    session.expire_all()

    repo = CampaignCRUD(session)
    assert (
        await repo.get_one_or_none(Campaign.id == ids["done"])
    ).status == CampaignStatusEnum.completed
    assert (
        await repo.get_one_or_none(Campaign.id == ids["empty"])
    ).status == CampaignStatusEnum.running


async def test_claim_respects_budget_windows_and_opt_outs(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)

    first = await _call(session, stack.agent.id, "+15551110008", campaign.id)
    second = await _call(session, stack.agent.id, "+15551110009", campaign.id)
    await ClientCRUD(session).create(
        {"phone": "+15551110010", "status": ClientStatusEnum.do_not_call}
    )
    opted_out = await _call(session, stack.agent.id, "+15551110010", campaign.id)
    not_due = await _call(
        session,
        stack.agent.id,
        "+15551110011",
        campaign.id,
        next_attempt_at=datetime.now() + timedelta(hours=1),
    )
    ids = {
        "first": first.id,
        "second": second.id,
        "opted_out": opted_out.id,
        "not_due": not_due.id,
    }
    await session.commit()

    attempt_ids = await claim_due_calls(session, budget=1)  # capacity for one
    await session.commit()

    assert len(attempt_ids) == 1
    claimed = await _fresh(session, ids["first"])  # oldest due row wins
    assert claimed.status == CallLifecycleEnum.calling and claimed.attempts_made == 1
    attempt = await CallAttemptCRUD(session).get_one_or_none(
        CallAttempt.id == attempt_ids[0]
    )
    assert (attempt.call_id, attempt.seq, attempt.status) == (
        ids["first"],
        1,
        CallStatusEnum.queued,
    )
    assert (await _fresh(session, ids["second"])).status == CallLifecycleEnum.pending
    # A late opt-out beats the uploaded row.
    assert (await _fresh(session, ids["opted_out"])).status == CallLifecycleEnum.blocked
    assert (await _fresh(session, ids["not_due"])).status == CallLifecycleEnum.pending


async def test_claim_honours_calling_hours(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    campaign.calling_hours = {
        "start": "00:00",
        "end": "00:00",
    }  # a window that is never open
    await _call(session, stack.agent.id, "+15551110012", campaign.id)
    await session.commit()

    assert await claim_due_calls(session, budget=10) == []


# ---------------------------------------------------------------------------
# Outcome-driven settling (post-call analysis).
# ---------------------------------------------------------------------------

from sqlalchemy import update as sql_update

from src.application.worker.dispatch import pending_analyses
from src.common.enums.campaign import CallOutcomeEnum
from src.models.client import Client

TALK = [{"role": "assistant", "content": "Hi!"}, {"role": "user", "content": "Hello."}]


async def _age_attempt(session, attempt_id: int, minutes: int) -> None:
    # Python datetimes, not SQL now(): ended_at is runner-written wall-clock
    # time in production, and settle compares it against the same clock.
    await session.execute(
        sql_update(CallAttempt)
        .where(CallAttempt.id == attempt_id)
        .values(ended_at=datetime.now() - timedelta(minutes=minutes))
    )
    await session.commit()


async def test_settle_waits_for_analysis_then_gives_up(org_uuid, session):
    stack = await seed_stack(session)
    call = await _call(session, stack.agent.id, "+15551110020")
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )
    await _age_attempt(session, attempt.id, minutes=2)
    call_id, attempt_id = call.id, attempt.id

    await settle_calls(session)
    await session.commit()
    # A fresh unanalyzed conversation is not settled — and is analysis-due.
    assert (await _fresh(session, call_id)).status == CallLifecycleEnum.calling
    assert attempt_id in await pending_analyses(session)

    await _age_attempt(session, attempt_id, minutes=20)
    await settle_calls(session)
    await session.commit()
    # Past the give-up window it folds without an outcome, and stops being due.
    row = await _fresh(session, call_id)
    assert row.status == CallLifecycleEnum.completed and row.outcome is None
    assert attempt_id not in await pending_analyses(session)


async def test_selected_offer_is_mirrored_onto_the_call(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    call = await _call(
        session,
        stack.agent.id,
        "+15551110022",
        campaign.id,
        bonuses=[{"title": "50% reload"}],
    )
    await _with_attempt(
        session,
        call,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.converted,
        selected_offer="50% reload",
    )

    await settle_calls(session)
    await session.commit()

    settled = await _fresh(session, call.id)
    assert settled.selected_offer == "50% reload"


async def test_do_not_call_blocks_the_client_everywhere(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    call = await _call(session, stack.agent.id, "+15551110021", campaign.id)
    await _with_attempt(
        session,
        call,
        CallStatusEnum.completed,
        messages=TALK,
        summary="Клиент просил больше не звонить.",
        outcome=CallOutcomeEnum.do_not_call,
    )
    # The same person queued in another campaign: must be canceled too.
    other_campaign = await _campaign(session, stack.agent.id)
    other = await _call(session, stack.agent.id, "+15551110021", other_campaign.id)
    ids = {"call": call.id, "other": other.id, "client": call.client_id}
    await session.commit()

    await settle_calls(session)
    await session.commit()

    settled = await _fresh(session, ids["call"])
    assert settled.status == CallLifecycleEnum.completed
    assert settled.outcome == CallOutcomeEnum.do_not_call
    client = await ClientCRUD(session).get_one_or_none(Client.id == ids["client"])
    assert client.status == ClientStatusEnum.do_not_call
    assert (await _fresh(session, ids["other"])).status == CallLifecycleEnum.canceled


async def test_call_later_uses_the_named_time_or_the_policy(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(
        session, stack.agent.id, retry={"no_answer_delay_seconds": 600}
    )
    recall_at = datetime.now() + timedelta(hours=5)

    named = await _call(session, stack.agent.id, "+15551110022", campaign.id)
    named.next_attempt_at = recall_at  # what the analysis task writes
    await _with_attempt(
        session,
        named,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.call_later,
    )

    unnamed = await _call(session, stack.agent.id, "+15551110023", campaign.id)
    await _with_attempt(
        session,
        unnamed,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.call_later,
    )

    # Manual call (no campaign): nothing re-dials it, outcome is still kept.
    manual = await _call(session, stack.agent.id, "+15551110024", None)
    await _with_attempt(
        session,
        manual,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.call_later,
    )
    ids = {"named": named.id, "unnamed": unnamed.id, "manual": manual.id}
    await session.commit()

    await settle_calls(session)
    await session.commit()

    named_row = await _fresh(session, ids["named"])
    assert named_row.status == CallLifecycleEnum.pending
    assert named_row.next_attempt_at == recall_at

    unnamed_row = await _fresh(session, ids["unnamed"])
    assert unnamed_row.status == CallLifecycleEnum.pending
    assert (
        timedelta(seconds=500)
        < (unnamed_row.next_attempt_at - datetime.now())
        <= timedelta(seconds=600)
    )

    manual_row = await _fresh(session, ids["manual"])
    assert manual_row.status == CallLifecycleEnum.completed
    assert manual_row.outcome == CallOutcomeEnum.call_later


async def test_unanswered_attempts_get_the_no_answer_outcome_without_analysis(
    org_uuid, session
):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 2})
    call = await _call(session, stack.agent.id, "+15551110025", campaign.id)
    attempt = await _with_attempt(session, call, CallStatusEnum.busy)
    ids = {"call": call.id, "attempt": attempt.id}

    await settle_calls(session)
    await session.commit()

    row = await _fresh(session, ids["call"])
    assert (
        row.status == CallLifecycleEnum.pending
        and row.outcome == CallOutcomeEnum.no_answer
    )
    session.expire_all()
    attempt = await CallAttemptCRUD(session).get_one_or_none(
        CallAttempt.id == ids["attempt"]
    )
    assert attempt.outcome == CallOutcomeEnum.no_answer
    # No conversation happened: never analysis-due (no bogus summaries).
    assert ids["attempt"] not in await pending_analyses(session)


async def _settled(session, call, attempt):
    ids = {"call": call.id, "attempt": attempt.id}
    await settle_calls(session)
    await session.commit()
    row = await _fresh(session, ids["call"])
    session.expire_all()
    attempt = await CallAttemptCRUD(session).get_one_or_none(
        CallAttempt.id == ids["attempt"]
    )
    return row, attempt


async def test_settle_rejected_retries_like_no_answer(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 2})
    call = await _call(session, stack.agent.id, "+15551110031", campaign.id)
    attempt = await _with_attempt(
        session,
        call,
        CallStatusEnum.rejected,
        provider_status="failed",
        provider_reason="603 Decline",
    )
    row, attempt = await _settled(session, call, attempt)
    assert row.status == CallLifecycleEnum.pending
    assert row.next_attempt_at > datetime.now()
    assert row.outcome == CallOutcomeEnum.no_answer
    assert attempt.outcome == CallOutcomeEnum.no_answer


async def test_settle_last_no_answer_attempt_exhausts_with_no_answer(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 1})
    call = await _call(session, stack.agent.id, "+15551110032", campaign.id)
    attempt = await _with_attempt(session, call, CallStatusEnum.no_answer)
    row, _ = await _settled(session, call, attempt)
    assert row.status == CallLifecycleEnum.exhausted
    assert row.next_attempt_at is None
    assert row.outcome == CallOutcomeEnum.no_answer


async def test_settle_system_error_keeps_failed_retry_policy(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 2})
    call = await _call(session, stack.agent.id, "+15551110033", campaign.id)
    attempt = await _with_attempt(
        session, call, CallStatusEnum.failed, error="provider reported failed: 503"
    )
    row, attempt = await _settled(session, call, attempt)
    assert row.status == CallLifecycleEnum.pending
    assert row.outcome is None  # a system error is not a "nobody answered"
    assert attempt.outcome is None


async def test_settle_failed_without_error_is_treated_as_no_answer(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 2})
    call = await _call(session, stack.agent.id, "+15551110034", campaign.id)
    attempt = await _with_attempt(session, call, CallStatusEnum.failed)
    row, attempt = await _settled(session, call, attempt)
    assert row.status == CallLifecycleEnum.pending
    assert row.outcome == CallOutcomeEnum.no_answer
    assert attempt.outcome == CallOutcomeEnum.no_answer


async def test_settle_invalid_number_closes_without_retry(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 5})
    call = await _call(session, stack.agent.id, "+15551110035", campaign.id)
    attempt = await _with_attempt(
        session, call, CallStatusEnum.invalid_number, provider_reason="404 Not Found"
    )
    row, attempt = await _settled(session, call, attempt)
    assert row.status == CallLifecycleEnum.exhausted
    assert row.next_attempt_at is None
    assert row.outcome == CallOutcomeEnum.wrong_number
    assert attempt.outcome == CallOutcomeEnum.wrong_number


async def test_retry_budget_counts_from_attempt_base_after_a_restart(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id, retry={"max_attempts": 2})
    # A restarted call: three attempts in history, budget starts afresh.
    restarted = await _call(
        session,
        stack.agent.id,
        "+15551110031",
        campaign.id,
        attempts_made=3,
        attempt_base=3,
    )
    for seq in (1, 2, 3):
        await CallAttemptCRUD(session).create(
            {"call_id": restarted.id, "seq": seq, "status": CallStatusEnum.no_answer}
        )
    await session.commit()
    call_id = restarted.id

    attempt_ids = await claim_due_calls(session, budget=1)
    await session.commit()
    attempt = await CallAttemptCRUD(session).get_one_or_none(
        CallAttempt.id == attempt_ids[0]
    )
    assert attempt.seq == 4  # continues the history, no UNIQUE(call_id, seq) clash

    await session.execute(
        update(CallAttempt)
        .where(CallAttempt.id == attempt.id)
        .values(status=CallStatusEnum.no_answer)
    )
    await session.commit()
    await settle_calls(session)
    await session.commit()
    row = await _fresh(session, call_id)
    assert row.status == CallLifecycleEnum.pending  # 4 - 3 = 1 < 2: one try left

    row.status = CallLifecycleEnum.calling
    row.attempts_made += 1
    await CallAttemptCRUD(session).create(
        {"call_id": call_id, "seq": row.attempts_made, "status": CallStatusEnum.busy}
    )
    await session.commit()
    await settle_calls(session)
    await session.commit()
    assert (await _fresh(session, call_id)).status == CallLifecycleEnum.exhausted

