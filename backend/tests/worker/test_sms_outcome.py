"""VOAD-80: a sent/delivered SMS makes the call's outcome ``sms_sent``.

Settle derives it for calls still ``calling``; ``mark_sms_sent`` corrects
calls that already settled when the SMS is confirmed late. ``do_not_call`` is
never overwritten, and a call with no confirmed SMS is left alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.common.enums.campaign import CallLifecycleEnum, CallOutcomeEnum
from src.common.enums.engine import CallStatusEnum, MessageStatusEnum
from src.models.call import CallAttempt
from src.repositories.call import CallAttemptCRUD, mark_sms_sent
from src.models.messaging import Messaging
from src.repositories.messaging import MessageCRUD, MessagingCRUD
from tests.support import seed_stack
from tests.worker.test_dispatch import (
    TALK,
    _call,
    _campaign,
    _fresh,
    _settled,
    _with_attempt,
)


async def _sms(session, call_id: int, status=MessageStatusEnum.sent):
    route = await MessagingCRUD(session).get_one_or_none(
        Messaging.is_active.is_(True)
    ) or await MessagingCRUD(
        session
    ).create(
        {"name": "r", "adapter": "twilio", "is_active": True, "sender": "VIRTA"}
    )
    message = await MessageCRUD(session).create(
        {
            "messaging_id": route.id,
            "call_id": call_id,
            "to_number": "+15550000001",
            "body": "link",
            "status": status,
        }
    )
    await session.commit()
    return message


async def _attempt_outcome(session, attempt_id: int):
    session.expire_all()
    row = await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == attempt_id)
    return row.outcome


async def test_settle_overwrites_call_later_and_schedules_no_callback(
    org_uuid, session
):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    call = await _call(session, stack.agent.id, "+15551110101", campaign.id)
    call.next_attempt_at = datetime.now() + timedelta(hours=3)
    attempt = await _with_attempt(
        session,
        call,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.call_later,
    )
    await _sms(session, call.id, MessageStatusEnum.delivered)

    row, att = await _settled(session, call, attempt)

    assert row.status == CallLifecycleEnum.completed
    assert row.outcome == CallOutcomeEnum.sms_sent
    assert row.next_attempt_at is None
    assert row.is_callback is False
    assert att.outcome == CallOutcomeEnum.sms_sent


async def test_settle_never_overwrites_do_not_call(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    call = await _call(session, stack.agent.id, "+15551110102", campaign.id)
    attempt = await _with_attempt(
        session,
        call,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.do_not_call,
    )
    await _sms(session, call.id)

    row, att = await _settled(session, call, attempt)

    assert row.outcome == CallOutcomeEnum.do_not_call
    assert att.outcome == CallOutcomeEnum.do_not_call


async def test_settle_without_a_sent_sms_is_unchanged(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    call = await _call(session, stack.agent.id, "+15551110103", campaign.id)
    attempt = await _with_attempt(
        session,
        call,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.interested,
    )
    # A failed send is not "an SMS was sent".
    await _sms(session, call.id, MessageStatusEnum.failed)

    row, att = await _settled(session, call, attempt)

    assert row.outcome == CallOutcomeEnum.interested
    assert att.outcome == CallOutcomeEnum.interested


async def test_late_sms_corrects_a_settled_call_and_cancels_the_callback(
    org_uuid, session
):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    call = await _call(session, stack.agent.id, "+15551110104", campaign.id)
    call.next_attempt_at = datetime.now() + timedelta(hours=3)
    attempt = await _with_attempt(
        session,
        call,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.call_later,
    )
    ids = {"call": call.id, "attempt": attempt.id}
    row, _ = await _settled(session, call, attempt)
    assert row.status == CallLifecycleEnum.pending  # callback scheduled

    await _sms(session, ids["call"], MessageStatusEnum.delivered)
    assert await mark_sms_sent(session, ids["call"]) is True
    await session.commit()

    row = await _fresh(session, ids["call"])
    assert row.status == CallLifecycleEnum.completed
    assert row.outcome == CallOutcomeEnum.sms_sent
    assert row.next_attempt_at is None
    assert await _attempt_outcome(session, ids["attempt"]) == CallOutcomeEnum.sms_sent


async def test_mark_sms_sent_is_idempotent_and_guarded(org_uuid, session):
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    ids = {}
    for name, outcome in (
        ("plain", CallOutcomeEnum.interested),
        ("dnc", CallOutcomeEnum.do_not_call),
    ):
        call = await _call(
            session, stack.agent.id, f"+1555111020{len(ids)}", campaign.id
        )
        attempt = await _with_attempt(
            session, call, CallStatusEnum.completed, messages=TALK, outcome=outcome
        )
        ids[name] = call.id
        await _settled(session, call, attempt)
        await _sms(session, call.id)

    assert await mark_sms_sent(session, ids["plain"]) is True
    assert await mark_sms_sent(session, ids["plain"]) is False  # already done
    assert await mark_sms_sent(session, ids["dnc"]) is False
    await session.commit()

    assert (await _fresh(session, ids["plain"])).outcome == CallOutcomeEnum.sms_sent
    assert (await _fresh(session, ids["dnc"])).outcome == CallOutcomeEnum.do_not_call


async def test_mark_sms_sent_leaves_a_live_call_alone(org_uuid, session):
    """While calling, settle owns the outcome; setting the attempt's now would
    skip its analysis (outcome doubles as the 'analysis done' marker)."""
    stack = await seed_stack(session)
    campaign = await _campaign(session, stack.agent.id)
    call = await _call(session, stack.agent.id, "+15551110105", campaign.id)
    attempt = await _with_attempt(
        session, call, CallStatusEnum.in_progress, messages=TALK
    )
    ids = {"call": call.id, "attempt": attempt.id}
    await _sms(session, ids["call"])

    assert await mark_sms_sent(session, ids["call"]) is False
    await session.commit()

    assert (await _fresh(session, ids["call"])).outcome is None
    assert await _attempt_outcome(session, ids["attempt"]) is None
