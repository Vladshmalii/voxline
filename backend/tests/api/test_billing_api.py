import asyncio
from datetime import datetime, timedelta

import pytest

from src.controller.dependencies.permission import _get_role
from src.models.billing import BalanceTransaction, OrganizationBalance
from src.models.call import Call, CallAttempt
from src.models.messaging import Message, Messaging


async def test_balances_and_deposits_are_independent(client):
    calls = await client.post(
        "/v1/billing/topup", json={"channel": "calls", "amount": 25}
    )
    assert calls.status_code == 200, calls.text
    assert calls.json()["call_balance"] == 25
    assert calls.json()["sms_balance"] == 0
    sms = await client.post("/v1/billing/topup", json={"channel": "sms", "amount": 10})
    assert sms.status_code == 200, sms.text
    summary = sms.json()
    assert summary["call_balance"] == 25 and summary["sms_balance"] == 10
    assert summary["call_deposited"] == 25 and summary["sms_deposited"] == 10
    assert summary["remaining_minutes"] == 250
    assert summary["remaining_sms"] == 500
    for channel, amount in [("calls", 25), ("sms", 10)]:
        history = (
            await client.get("/v1/billing/transactions", params={"channel": channel})
        ).json()
        assert history["count"] == 1
        assert history["data"][0]["channel"] == channel
        assert history["data"][0]["amount"] == amount
        assert history["data"][0]["balance_after"] == amount


async def test_legacy_topup_defaults_to_calls(client):
    response = await client.post("/v1/billing/topup", json={"amount": 5})
    assert response.status_code == 200
    assert response.json()["balance"] == response.json()["call_balance"] == 5
    assert response.json()["sms_balance"] == 0


async def test_summary_separates_costs_and_counts_retrying_calls_once(client, session):
    route = Messaging(name="billing", adapter="mamonty")
    call = Call()
    balance = OrganizationBalance(
        call_balance=30, sms_balance=4, cost_per_minute=0.5, cost_per_sms=0.25
    )
    session.add_all([route, call, balance])
    await session.flush()
    start = datetime(2026, 1, 1)
    for seq in [1, 2]:
        session.add(
            CallAttempt(
                call_id=call.id,
                seq=seq,
                answered_at=start,
                ended_at=start + timedelta(seconds=60),
            )
        )
    for status in ["queued", "sent", "delivered", "undelivered", "failed", "canceled"]:
        session.add(
            Message(
                messaging_id=route.id,
                to_number="+49123456789",
                body="test",
                status=status,
            )
        )
    await session.commit()
    response = await client.get("/v1/billing/summary")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["total_calls_count"] == 1
    assert summary["total_minutes_used"] == 2
    assert summary["total_sms_sent"] == 3
    assert summary["call_spent"] == 1
    assert summary["sms_spent"] == 0.75
    assert summary["total_spent"] == 1.75
    assert summary["call_balance"] == 30 and summary["sms_balance"] == 4


async def test_transaction_filters_and_pagination_are_applied_in_database(
    client, session
):
    for channel in ["calls", "sms"]:
        session.add_all(
            [
                BalanceTransaction(
                    channel=channel, type="deposit", amount=10, description="deposit"
                ),
                BalanceTransaction(
                    channel=channel,
                    type=f"{'call' if channel == 'calls' else 'sms'}_usage",
                    amount=-2,
                    description="usage",
                ),
            ]
        )
    await session.commit()
    history = (
        await client.get(
            "/v1/billing/transactions",
            params={"channel": "sms", "limit": 1, "offset": 1},
        )
    ).json()
    assert history["count"] == 2 and len(history["data"]) == 1
    assert history["data"][0]["channel"] == "sms"
    charges = (
        await client.get(
            "/v1/billing/transactions", params={"channel": "calls", "type": "charges"}
        )
    ).json()
    assert charges["count"] == 1 and charges["data"][0]["amount"] == -2


async def test_tariff_change_does_not_change_other_rate_or_balance(client):
    await client.post("/v1/billing/topup", json={"channel": "sms", "amount": 10})
    response = await client.patch("/v1/billing/tariffs", json={"cost_per_sms": 0})
    assert response.status_code == 200
    assert response.json()["cost_per_minute"] == 0.1
    assert response.json()["sms_balance"] == 10
    assert response.json()["remaining_sms"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"channel": "other", "amount": 10},
        {"channel": "sms", "amount": -1},
        {"amount": 0},
    ],
)
async def test_invalid_topups(client, payload):
    assert (await client.post("/v1/billing/topup", json=payload)).status_code == 422


async def test_invalid_channel_filter(client):
    assert (
        await client.get("/v1/billing/transactions", params={"channel": "other"})
    ).status_code == 422


async def test_simultaneous_first_deposits_preserve_both_balances(client):
    responses = await asyncio.gather(
        *[
            client.post("/v1/billing/topup", json={"channel": channel, "amount": 1})
            for channel in ["calls", "sms", "calls", "sms", "calls", "sms"]
        ]
    )
    assert all(response.status_code == 200 for response in responses)
    summary = (await client.get("/v1/billing/summary")).json()
    assert summary["call_balance"] == summary["sms_balance"] == 3
    for channel in ["calls", "sms"]:
        history = (
            await client.get("/v1/billing/transactions", params={"channel": channel})
        ).json()
        assert history["count"] == 3
        assert sorted(row["balance_after"] for row in history["data"]) == [1, 2, 3]


async def test_sms_availability_does_not_round_down_a_whole_message(client):
    await client.patch("/v1/billing/tariffs", json={"cost_per_sms": 0.1})
    response = await client.post(
        "/v1/billing/topup", json={"channel": "sms", "amount": 0.3}
    )
    assert response.json()["remaining_sms"] == 3


@pytest.mark.parametrize("role", ["owner", "staff", "viewer", "none"])
async def test_stats_and_split_billing_keep_existing_role_permissions(
    client, app, role
):
    previous = app.dependency_overrides[_get_role]
    app.dependency_overrides[_get_role] = lambda: role
    try:
        for path in [
            "/v1/sms/stats/overview",
            "/v1/billing/summary",
            "/v1/billing/transactions?channel=sms",
        ]:
            assert (await client.get(path)).status_code == (
                403 if role == "none" else 200
            )
        for channel in ["calls", "sms"]:
            response = await client.post(
                "/v1/billing/topup", json={"channel": channel, "amount": 1}
            )
            assert response.status_code == (200 if role == "owner" else 403)
    finally:
        app.dependency_overrides[_get_role] = previous


@pytest.mark.parametrize("role", ["owner", "staff", "viewer"])
async def test_client_roles_cannot_change_tariffs_or_see_the_sms_rate(client, app, role):
    previous = app.dependency_overrides[_get_role]
    app.dependency_overrides[_get_role] = lambda: role
    try:
        response = await client.patch("/v1/billing/tariffs", json={"cost_per_minute": 9})
        assert response.status_code == 403
        summary = (await client.get("/v1/billing/summary")).json()
        assert summary["cost_per_sms"] is None
        assert summary["cost_per_minute"] == 0.1
    finally:
        app.dependency_overrides[_get_role] = previous
    # Internal roles keep the rate and the write access.
    assert (await client.get("/v1/billing/summary")).json()["cost_per_sms"] == 0.02
    assert (
        await client.patch("/v1/billing/tariffs", json={"cost_per_minute": 0.1})
    ).status_code == 200


async def test_minutes_only_closes_billing_for_clients_but_not_admins(client, app):
    assert (
        await client.patch("/v1/billing/tariffs", json={"minutes_only": True})
    ).json()["minutes_only"] is True
    previous = app.dependency_overrides[_get_role]
    app.dependency_overrides[_get_role] = lambda: "owner"
    try:
        for path in ["/v1/billing/summary", "/v1/billing/transactions"]:
            assert (await client.get(path)).status_code == 403
        assert (
            await client.post("/v1/billing/topup", json={"channel": "calls", "amount": 1})
        ).status_code == 403
        assert (await client.get("/v1/me")).json()["billing_enabled"] is False
    finally:
        app.dependency_overrides[_get_role] = previous
    assert (await client.get("/v1/billing/summary")).status_code == 200
    assert (await client.get("/v1/me")).json()["billing_enabled"] is True
    await client.patch("/v1/billing/tariffs", json={"minutes_only": False})
