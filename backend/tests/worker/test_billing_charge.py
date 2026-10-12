"""Spending is real: answered calls debit the balance once, and no funds means no new dials."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src.application.services.billing import BillingService
from src.application.services.call import CallService, OriginateError
from src.common.enums.campaign import CallLifecycleEnum
from src.common.enums.engine import CallStatusEnum
from src.models.billing import BalanceTransaction, OrganizationBalance
from src.repositories.billing import OrganizationBalanceCRUD
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.client import ClientCRUD
from src.schemas.admin import SCallCreate
from tests.support import fund, seed_stack


async def _answered_attempt(session, agent_id: int, seconds: int):
    client = await ClientCRUD(session).upsert_by_phone("+15551110009")
    call = await CallCRUD(session).create(
        {
            "client_id": client.id,
            "agent_id": agent_id,
            "status": CallLifecycleEnum.calling,
            "attempts_made": 1,
        }
    )
    start = datetime.now() - timedelta(minutes=10)
    attempt = await CallAttemptCRUD(session).create(
        {
            "call_id": call.id,
            "seq": 1,
            "status": CallStatusEnum.completed,
            "answered_at": start,
            "ended_at": start + timedelta(seconds=seconds),
        }
    )
    await session.commit()
    return attempt


async def _balance(session) -> OrganizationBalance:
    session.expire_all()
    return (await session.execute(select(OrganizationBalance))).scalar_one()


async def test_an_answered_call_is_debited_once(session):
    stack = await seed_stack(session)
    await fund(session, calls=10.0)
    row = await _balance(session)
    row.cost_per_minute = 0.5
    await session.commit()
    attempt = await _answered_attempt(session, stack.agent.id, seconds=120)

    billing = BillingService(session)
    assert await billing.charge_call(attempt.id) is True
    assert await billing.charge_call(attempt.id) is False  # same attempt: no double bill
    await session.commit()

    assert (await _balance(session)).call_balance == pytest.approx(9.0)  # 2 min × 0.5
    charges = (await session.execute(select(BalanceTransaction))).scalars().all()
    assert [(c.type, c.amount, c.channel) for c in charges] == [
        ("call_usage", pytest.approx(-1.0), "calls")
    ]


async def test_an_unanswered_attempt_costs_nothing(session):
    stack = await seed_stack(session)
    await fund(session, calls=10.0)
    attempt = await _answered_attempt(session, stack.agent.id, seconds=60)
    await CallAttemptCRUD(session).update(
        type(attempt).id == attempt.id, data={"answered_at": None}
    )
    await session.commit()

    assert await BillingService(session).charge_call(attempt.id) is False
    assert (await _balance(session)).call_balance == 10.0


async def test_no_funds_means_no_new_call(session):
    stack = await seed_stack(session)
    await fund(session, calls=0.0)

    with pytest.raises(OriginateError, match="insufficient"):
        await CallService(session).originate(
            SCallCreate(agent_id=stack.agent.id, to_number="+15551112222")
        )


async def test_minutes_only_clients_are_never_gated(session):
    await fund(session, calls=0.0, sms=0.0)
    row = await _balance(session)
    row.minutes_only = True
    await session.commit()

    crud = OrganizationBalanceCRUD(session)
    assert await crud.has_funds("calls") and await crud.has_funds("sms")
