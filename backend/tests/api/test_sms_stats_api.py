from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from src.common.enums.engine import MessageStatusEnum
from src.models.messaging import Message, Messaging


async def seed_messages(session):
    route = Messaging(name="stats", adapter="mamonty", is_active=True)
    other_route = Messaging(name="other", adapter="mamonty")
    session.add_all([route, other_route])
    await session.flush()
    today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    for status in MessageStatusEnum:
        session.add(
            Message(
                messaging_id=route.id,
                to_number="+49123456789",
                body="test",
                status=status,
                segments=2,
                created_at=today,
            )
        )
    session.add(
        Message(
            messaging_id=other_route.id,
            to_number="+49123456780",
            body="old",
            status=MessageStatusEnum.delivered,
            segments=1,
            created_at=today - timedelta(days=2),
        )
    )
    await session.commit()
    return route.id, today.date()


async def test_empty_sms_stats(client):
    response = await client.get("/v1/sms/stats/overview")
    assert response.status_code == 200, response.text
    stats = response.json()
    assert stats["total"] == stats["today"] == stats["segments"] == 0
    assert stats["delivery_rate"] is None
    assert len(stats["by_status"]) == 6
    assert all(item["count"] == 0 for item in stats["by_status"])


async def test_statuses_and_route_filters(client, session):
    route_id, _ = await seed_messages(session)
    stats = (await client.get("/v1/sms/stats/overview")).json()
    assert stats["total"] == 7
    assert stats["today"] == 6
    assert stats["sent"] == 4
    assert stats["delivered"] == 2
    assert stats["errors"] == 2
    assert stats["pending"] == 2
    assert stats["segments"] == 13
    assert stats["delivery_rate"] == pytest.approx(2 / 7)
    filtered = (
        await client.get("/v1/sms/stats/overview", params={"messaging_id": route_id})
    ).json()
    assert filtered["total"] == 6
    assert filtered["delivery_rate"] == pytest.approx(1 / 6)
    number = (
        await client.get("/v1/sms/stats/overview", params={"to": "+49123456780"})
    ).json()
    assert number["total"] == 1
    assert number["today"] == 0
    assert number["delivery_rate"] == 1
    combined = (
        await client.get(
            "/v1/sms/stats/overview",
            params={"messaging_id": route_id, "to": "+49123456780"},
        )
    ).json()
    assert combined["total"] == 0
    assert combined["delivery_rate"] is None


async def test_delivery_rate_includes_sending_failures_and_pending_messages(
    client, session
):
    route = Messaging(name="delivery-rate", adapter="mamonty")
    session.add(route)
    await session.flush()
    for status, count in (
        (MessageStatusEnum.delivered, 6),
        (MessageStatusEnum.failed, 14),
        (MessageStatusEnum.sent, 1),
    ):
        session.add_all(
            [
                Message(
                    messaging_id=route.id,
                    to_number="+49123456789",
                    body="test",
                    status=status,
                )
                for _ in range(count)
            ]
        )
    await session.commit()

    response = await client.get("/v1/sms/stats/overview")
    assert response.status_code == 200, response.text
    stats = response.json()
    assert stats["total"] == 21
    assert stats["delivered"] == 6
    assert stats["errors"] == 14
    assert stats["pending"] == 1
    assert stats["delivery_rate"] == pytest.approx(6 / 21)


async def test_only_sending_failures_have_zero_delivery_rate(client, session):
    route = Messaging(name="failed", adapter="mamonty")
    session.add(route)
    await session.flush()
    session.add(
        Message(
            messaging_id=route.id,
            to_number="+49123456789",
            body="test",
            status=MessageStatusEnum.failed,
        )
    )
    await session.commit()
    stats = (await client.get("/v1/sms/stats/overview")).json()
    assert stats["total"] == 1
    assert stats["delivery_rate"] == 0


async def test_daily_counts_fill_gaps_and_use_inclusive_creation_dates(client, session):
    route_id, today = await seed_messages(session)
    params = {"date_from": str(today - timedelta(days=2)), "date_to": str(today)}
    response = await client.get("/v1/sms/stats/timeseries", params=params)
    assert response.status_code == 200, response.text
    assert response.json()["days"] == [
        {"date": params["date_from"], "total": 1, "delivered": 1, "failed": 0},
        {
            "date": str(today - timedelta(days=1)),
            "total": 0,
            "delivered": 0,
            "failed": 0,
        },
        {"date": str(today), "total": 6, "delivered": 1, "failed": 2},
    ]
    filtered = (
        await client.get(
            "/v1/sms/stats/timeseries", params={**params, "messaging_id": route_id}
        )
    ).json()
    assert filtered["days"][0]["total"] == 0
    single = (
        await client.get(
            "/v1/sms/stats/timeseries",
            params={"date_from": str(today), "date_to": str(today)},
        )
    ).json()
    assert len(single["days"]) == 1 and single["days"][0]["total"] == 6


async def test_delivery_callbacks_are_reflected_in_stats(client, session):
    route = Messaging(name="stats", adapter="mamonty")
    session.add(route)
    await session.flush()
    message = Message(
        messaging_id=route.id,
        to_number="+49123456789",
        body="test",
        status=MessageStatusEnum.sent,
    )
    session.add(message)
    await session.commit()
    before = (await client.get("/v1/sms/stats/overview")).json()
    assert before["pending"] == 1 and before["delivery_rate"] == 0
    await session.execute(
        update(Message)
        .where(Message.id == message.id)
        .values(status=MessageStatusEnum.delivered)
    )
    await session.commit()
    after = (await client.get("/v1/sms/stats/overview")).json()
    assert after["total"] == 1 and after["pending"] == 0
    assert after["delivered"] == 1 and after["delivery_rate"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-01-02", "date_to": "2026-01-01"},
        {"date_from": "2026-01-01", "date_to": "2026-04-01"},
        {"date_from": "bad", "date_to": "2026-01-01"},
        {},
    ],
)
async def test_invalid_ranges(client, params):
    assert (
        await client.get("/v1/sms/stats/timeseries", params=params)
    ).status_code == 422


async def test_exactly_ninety_days_allowed(client):
    response = await client.get(
        "/v1/sms/stats/timeseries",
        params={"date_from": "2026-01-01", "date_to": "2026-03-31"},
    )
    assert response.status_code == 200
    assert len(response.json()["days"]) == 90
