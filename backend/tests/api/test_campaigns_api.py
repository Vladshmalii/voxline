"""Campaigns: template validation at the edges, upload verdicts, lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.common.enums.campaign import CallLifecycleEnum, ClientStatusEnum
from src.models.call import Call
from src.models.client import Client
from src.repositories.call import CallCRUD
from src.repositories.client import ClientCRUD
from tests.support import seed_stack


async def _campaign(client, agent_id: int, **extra) -> dict:
    response = await client.post(
        "/v1/campaigns",
        json={
            "name": "welcome-back",
            "agent_id": agent_id,
            "call_script": "Offer {{ name }} the {{ bonuses[0].code }} bonus.",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_validates_the_template(client, session):
    stack = await seed_stack(session)
    await session.commit()

    broken = await client.post(
        "/v1/campaigns",
        json={"name": "x", "agent_id": stack.agent.id, "call_script": "{% for %}"},
    )
    assert (
        broken.status_code == 422 and "call_script: line 1" in broken.json()["detail"]
    )

    body = await _campaign(client, stack.agent.id)
    assert body["status"] == "draft"
    # Effective sections: defaults filled in, ready for a configuration UI.
    assert body["retry"]["max_attempts"] == 3
    assert body["calling_hours"]["timezone"] == "UTC"


async def test_upload_verdicts_every_row(client, session):
    stack = await seed_stack(session)
    await ClientCRUD(session).create(
        {"phone": "+15550009999", "status": ClientStatusEnum.do_not_call}
    )
    await session.commit()
    campaign = await _campaign(client, stack.agent.id)

    rows = [
        {"phone": "+15551110001", "name": "Anna", "bonuses": [{"code": "WB50"}]},
        {"phone": "junk"},
        # Strict validation: the template needs bonuses[0], this row has none.
        {"phone": "+15551110002", "name": "Ben"},
        {"phone": "+15550009999", "name": "Opted Out", "bonuses": [{"code": "WB50"}]},
        # Same phone as the first row: one campaign dials a person once.
        {"phone": "+1 555 111 0001", "name": "Anna", "bonuses": [{"code": "WB50"}]},
    ]
    response = await client.post(f"/v1/campaigns/{campaign['id']}/contacts", json=rows)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["accepted"], body["rejected"]) == (1, 4)

    accepted = [r for r in body["results"] if r["error"] is None]
    errors = {r["phone"]: r["error"] for r in body["results"] if r["error"]}
    assert len(accepted) == 1 and accepted[0]["phone"] == "+15551110001"
    assert "not a dialable" in errors["junk"]
    assert "call_script" in errors["+15551110002"]
    assert "not callable" in errors["+15550009999"]
    assert "already in this campaign" in errors["+15551110001"]

    call = await CallCRUD(session).get_one_or_none(Call.id == accepted[0]["call_id"])
    assert call.status == CallLifecycleEnum.pending
    assert call.bonuses == [{"code": "WB50"}] and call.campaign_id == campaign["id"]
    assert (
        await ClientCRUD(session).get_one_or_none(Client.phone == "+15551110001")
    ).name == "Anna"


async def test_lifecycle_start_pause_complete(client, session):
    stack = await seed_stack(session)
    await session.commit()
    campaign = await _campaign(client, stack.agent.id)
    cid = campaign["id"]

    started = await client.post(f"/v1/campaigns/{cid}/start")
    assert started.status_code == 200 and started.json()["status"] == "running"

    paused = await client.post(f"/v1/campaigns/{cid}/pause")
    assert paused.status_code == 200 and paused.json()["status"] == "paused"

    rows = [{"phone": "+15551110003", "bonuses": [{"code": "WB50"}]}]
    assert (
        await client.post(f"/v1/campaigns/{cid}/contacts", json=rows)
    ).status_code == 200

    completed = await client.post(f"/v1/campaigns/{cid}/complete")
    assert completed.status_code == 200 and completed.json()["status"] == "completed"
    # Completing by hand cancels what was never dialed.
    session.expire_all()
    leftover = await CallCRUD(session).get_one_or_none(Call.campaign_id == cid)
    assert leftover.status == CallLifecycleEnum.canceled

    # A completed campaign accepts neither uploads nor a restart.
    assert (
        await client.post(f"/v1/campaigns/{cid}/contacts", json=rows)
    ).status_code == 422
    assert (await client.post(f"/v1/campaigns/{cid}/start")).status_code == 422


async def test_start_refuses_an_undialable_setup(client, session):
    stack = await seed_stack(session, agent_active=False)
    await session.commit()
    campaign = await _campaign(client, stack.agent.id)

    response = await client.post(f"/v1/campaigns/{campaign['id']}/start")
    assert response.status_code == 422 and "not active" in response.json()["detail"]


async def _finished_campaign(client, session, agent_id: int, **extra):
    """A completed campaign with one call in each interesting state."""
    campaign = await _campaign(client, agent_id, **extra)
    cid = campaign["id"]
    calls = {}
    specs = {
        "exhausted": (CallLifecycleEnum.exhausted, ClientStatusEnum.active),
        "canceled": (CallLifecycleEnum.canceled, ClientStatusEnum.active),
        "completed": (CallLifecycleEnum.completed, ClientStatusEnum.active),
        "blocked": (CallLifecycleEnum.blocked, ClientStatusEnum.active),
        "dnc": (CallLifecycleEnum.exhausted, ClientStatusEnum.do_not_call),
    }
    for i, (name, (status, client_status)) in enumerate(specs.items()):
        person = await ClientCRUD(session).upsert_by_phone(f"+1555222000{i}")
        person.status = client_status
        row = await CallCRUD(session).create(
            {
                "client_id": person.id,
                "campaign_id": cid,
                "agent_id": agent_id,
                "status": status,
                "attempts_made": 2,
                "next_attempt_at": datetime.now() + timedelta(hours=1),
                "is_callback": True,
                "tags": ["x"],
            }
        )
        calls[name] = row.id
    await session.commit()
    assert (await client.post(f"/v1/campaigns/{cid}/complete")).status_code == 200
    return cid, calls


async def _call_row(session, call_id: int) -> Call:
    session.expire_all()
    return await CallCRUD(session).get_one_or_none(Call.id == call_id)


async def test_restart_requeues_only_exhausted_and_canceled_active_calls(
    client, session
):
    stack = await seed_stack(session)
    await session.commit()
    cid, calls = await _finished_campaign(client, session, stack.agent.id)

    response = await client.post(f"/v1/campaigns/{cid}/restart")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"

    for name in ("exhausted", "canceled"):
        row = await _call_row(session, calls[name])
        assert row.status == CallLifecycleEnum.pending
        assert row.next_attempt_at is None and row.is_callback is False
        # History stays (seq keeps counting); the budget restarts from here.
        assert (row.attempts_made, row.attempt_base) == (2, 2)
    for name, status in (
        ("completed", CallLifecycleEnum.completed),
        ("blocked", CallLifecycleEnum.blocked),
        ("dnc", CallLifecycleEnum.exhausted),  # do-not-call client untouched
    ):
        row = await _call_row(session, calls[name])
        assert row.status == status and row.attempt_base == 0
        assert row.next_attempt_at is not None


async def test_restart_is_refused_unless_completed_or_error(client, session):
    stack = await seed_stack(session)
    await session.commit()
    campaign = await _campaign(client, stack.agent.id)
    cid = campaign["id"]

    assert (await client.post(f"/v1/campaigns/{cid}/restart")).status_code == 422  # draft
    assert (await client.post(f"/v1/campaigns/{cid}/start")).status_code == 200
    refused = await client.post(f"/v1/campaigns/{cid}/restart")
    assert refused.status_code == 422 and "restart refused" in refused.json()["detail"]

    assert (await client.post(f"/v1/campaigns/{cid}/error")).status_code == 200
    assert (await client.post(f"/v1/campaigns/{cid}/restart")).status_code == 200


async def test_second_restart_is_refused_without_a_double_reset(client, session):
    stack = await seed_stack(session)
    await session.commit()
    cid, calls = await _finished_campaign(client, session, stack.agent.id)

    assert (await client.post(f"/v1/campaigns/{cid}/restart")).status_code == 200
    again = await client.post(f"/v1/campaigns/{cid}/restart")
    assert again.status_code == 422 and "running" in again.json()["detail"]
    assert (await _call_row(session, calls["exhausted"])).attempt_base == 2


async def test_restart_refuses_an_ended_window(client, session):
    stack = await seed_stack(session)
    await session.commit()
    past = (datetime.now() - timedelta(days=1)).isoformat()
    cid, _ = await _finished_campaign(client, session, stack.agent.id, ends_at=past)
    refused = await client.post(f"/v1/campaigns/{cid}/restart")
    assert refused.status_code == 422 and "ends_at" in refused.json()["detail"]


async def test_restart_refuses_an_undialable_setup(client, session):
    stack = await seed_stack(session)
    await session.commit()
    cid, _ = await _finished_campaign(client, session, stack.agent.id)
    # The agent is switched off after the campaign finished.
    stack.agent.is_active = False
    await session.commit()
    refused = await client.post(f"/v1/campaigns/{cid}/restart")
    assert refused.status_code == 422 and "not active" in refused.json()["detail"]

