"""Calls: originate refusals, the created rows, cancel semantics, listing."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.common.enums.campaign import CallLifecycleEnum, ClientStatusEnum
from src.common.enums.engine import CallStatusEnum, MessageStatusEnum
from src.models.call import Call, CallAttempt
from src.models.client import Client
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.client import ClientCRUD
from src.repositories.messaging import MessageCRUD, MessagingCRUD
from tests.support import queue_depth, seed_stack


async def test_originate_refuses_early(client, session):
    missing = await client.post(
        "/v1/calls", json={"agent_id": 99, "to_number": "+15551112222"}
    )
    assert missing.status_code == 422 and "not found" in missing.json()["detail"]

    inactive = await seed_stack(session, agent_active=False)
    await session.commit()
    response = await client.post(
        "/v1/calls", json={"agent_id": inactive.agent.id, "to_number": "+15551112222"}
    )
    assert response.status_code == 422 and "not active" in response.json()["detail"]


async def test_originate_requires_a_live_trunk(client, session):
    no_trunk = await seed_stack(session, with_telephony=False)
    await session.commit()
    response = await client.post(
        "/v1/calls", json={"agent_id": no_trunk.agent.id, "to_number": "+15551112222"}
    )
    assert response.status_code == 422 and "telephony" in response.json()["detail"]


async def test_originate_refuses_junk_numbers_and_opted_out_clients(client, session):
    stack = await seed_stack(session)
    await ClientCRUD(session).create(
        {"phone": "+15550009999", "status": ClientStatusEnum.do_not_call}
    )
    await session.commit()

    junk = await client.post(
        "/v1/calls", json={"agent_id": stack.agent.id, "to_number": "not-a-number"}
    )
    assert junk.status_code == 422 and "not a dialable" in junk.json()["detail"]

    opted_out = await client.post(
        "/v1/calls", json={"agent_id": stack.agent.id, "to_number": "+15550009999"}
    )
    assert opted_out.status_code == 422 and "not callable" in opted_out.json()["detail"]


async def test_originate_creates_client_call_and_attempt(client, session):
    stack = await seed_stack(session)
    await session.commit()

    response = await client.post(
        "/v1/calls",
        json={
            "agent_id": stack.agent.id,
            "to_number": "+1 (555) 111-2222",  # normalized before it lands anywhere
            "name": "Anna",
            "attributes": {"vip": True},
            "bonuses": [{"code": "WB50"}],
            "overrides": {"language": "override", "voice": "pinned"},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "calling"
    assert body["from_number"] == "+15550000001"  # defaulted from the trunk's caller id
    assert body["bonuses"] == [{"code": "WB50"}] and body["attributes"] == {"vip": True}
    assert body["overrides"] == {"language": "override", "voice": "pinned"}

    # The attempt snapshots what this leg would run with — support reads this.
    assert len(body["attempts"]) == 1
    attempt = body["attempts"][0]
    assert attempt["seq"] == 1 and attempt["status"] == "queued"
    assert "tts=qwen3_tts:pinned" in attempt["profile_summary"]

    session.expire_all()
    row = await ClientCRUD(session).get_one_or_none(Client.phone == "+15551112222")
    assert row is not None and row.name == "Anna"
    assert row.id == body["client_id"]

    # Commit-then-enqueue: the dial task is already on the queue.
    assert await queue_depth() == 1


async def test_list_shows_the_latest_attempts_duration_and_client(client, session):
    stack = await seed_stack(session)
    dialed = await ClientCRUD(session).upsert_by_phone("+15559990000")
    call = await CallCRUD(session).create(
        {
            "agent_id": stack.agent.id,
            "client_id": dialed.id,
            "status": CallLifecycleEnum.completed,
        }
    )
    answered_at = datetime.now() - timedelta(seconds=42)
    await CallAttemptCRUD(session).create(
        {
            "call_id": call.id,
            "seq": 1,
            "status": CallStatusEnum.completed,
            "answered_at": answered_at,
            "ended_at": answered_at + timedelta(seconds=17),
        }
    )
    await session.commit()

    response = await client.get("/v1/calls")
    assert response.status_code == 200
    (row,) = [c for c in response.json()["data"] if c["id"] == call.id]
    assert row["duration_seconds"] == 17
    assert row["client"]["phone"] == "+15559990000"


async def test_list_counts_only_sent_and_delivered_sms_per_call(client, session):
    stack = await seed_stack(session)
    dialed = await ClientCRUD(session).upsert_by_phone("+15559990001")
    call = await CallCRUD(session).create(
        {
            "agent_id": stack.agent.id,
            "client_id": dialed.id,
            "status": CallLifecycleEnum.completed,
        }
    )
    quiet = await CallCRUD(session).create(
        {
            "agent_id": stack.agent.id,
            "client_id": dialed.id,
            "status": CallLifecycleEnum.completed,
        }
    )
    route = await MessagingCRUD(session).create(
        {"name": "route", "adapter": "twilio", "is_active": True}
    )
    for status in (
        MessageStatusEnum.sent,
        MessageStatusEnum.delivered,
        MessageStatusEnum.queued,
        MessageStatusEnum.failed,
        MessageStatusEnum.undelivered,
        MessageStatusEnum.canceled,
    ):
        await MessageCRUD(session).create(
            {
                "messaging_id": route.id,
                "call_id": call.id,
                "to_number": "+15559990001",
                "body": "hi",
                "status": status,
            }
        )
    await session.commit()

    response = await client.get("/v1/calls")
    assert response.status_code == 200
    rows = {c["id"]: c for c in response.json()["data"]}
    assert rows[call.id]["sms_sent"] == 2
    assert rows[quiet.id]["sms_sent"] == 0


async def test_list_sorts_by_duration_despite_it_being_a_python_property(
    client, session
):
    """duration_seconds has no column; sorting by it needs its own SQL expression."""
    stack = await seed_stack(session)
    short_call = await CallCRUD(session).create(
        {"agent_id": stack.agent.id, "status": CallLifecycleEnum.completed}
    )
    long_call = await CallCRUD(session).create(
        {"agent_id": stack.agent.id, "status": CallLifecycleEnum.completed}
    )
    now = datetime.now()
    await CallAttemptCRUD(session).create(
        {
            "call_id": short_call.id,
            "seq": 1,
            "status": CallStatusEnum.completed,
            "answered_at": now,
            "ended_at": now + timedelta(seconds=5),
        }
    )
    await CallAttemptCRUD(session).create(
        {
            "call_id": long_call.id,
            "seq": 1,
            "status": CallStatusEnum.completed,
            "answered_at": now,
            "ended_at": now + timedelta(seconds=50),
        }
    )
    await session.commit()

    ascending = await client.get("/v1/calls", params={"sort": "duration"})
    assert ascending.status_code == 200
    ids = [
        c["id"]
        for c in ascending.json()["data"]
        if c["id"] in (short_call.id, long_call.id)
    ]
    assert ids == [short_call.id, long_call.id]

    descending = await client.get("/v1/calls", params={"sort": "-duration"})
    assert descending.status_code == 200
    ids = [
        c["id"]
        for c in descending.json()["data"]
        if c["id"] in (short_call.id, long_call.id)
    ]
    assert ids == [long_call.id, short_call.id]


async def test_cancel_only_before_the_leg_exists(client, session, org_uuid):
    stack = await seed_stack(session)
    await session.commit()
    # Plain int, captured before any expire_all(): reading it off the expired
    # ORM instance later would be sync IO → MissingGreenlet.
    agent_id = stack.agent.id
    call_id = (
        await client.post(
            "/v1/calls", json={"agent_id": agent_id, "to_number": "+15551112222"}
        )
    ).json()["id"]

    canceled = await client.post(f"/v1/calls/{call_id}/cancel")
    assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
    session.expire_all()
    attempt = await CallAttemptCRUD(session).get_one_or_none(
        CallAttempt.call_id == call_id
    )
    assert attempt.status == CallStatusEnum.canceled  # the queued leg went with it

    again = await client.post(f"/v1/calls/{call_id}/cancel")
    assert again.status_code == 409  # terminal states stay put

    # Once the worker owns the leg (dialing), cancel is no longer the API's call.
    second = (
        await client.post(
            "/v1/calls", json={"agent_id": agent_id, "to_number": "+15551113333"}
        )
    ).json()["id"]
    await CallAttemptCRUD(session).update(
        CallAttempt.call_id == second, data={"status": CallStatusEnum.dialing}
    )
    await session.commit()
    assert (await client.post(f"/v1/calls/{second}/cancel")).status_code == 409
    session.expire_all()
    assert (
        await CallCRUD(session).get_one_or_none(Call.id == second)
    ).status == CallLifecycleEnum.calling
