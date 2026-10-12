"""The hooks surface: media socket admission and status-webhook guards.

The WebSocket tests exercise admission only — token, single-use claim, runner
handoff — with the runner and the redis claim faked at the module seam
(starlette's TestClient runs the app in its own event loop, where the
fixture-loop redis client must not be touched; the real claim semantics are
covered in test_registry). The status webhook goes through the full stack.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import src.main_hooks
from src.application.worker import registry
from src.common.enums.campaign import CallLifecycleEnum
from src.common.enums.engine import CallDirectionEnum, CallStatusEnum
from src.models.call import CallAttempt
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.client import ClientCRUD
from src.settings import SETTINGS
from tests.support import seed_stack


@pytest.fixture
def ws_client():
    # No context manager: the lifespan (startup/drain/shutdown) is not wanted here.
    return TestClient(src.main_hooks.app)


def test_media_socket_rejects_bad_tokens(ws_client, monkeypatch):
    async def must_not_claim(_uuid):  # a bad token must be refused before any lookup
        raise AssertionError("claim attempted with a bad token")

    monkeypatch.setattr(registry, "claim", must_not_claim)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        ws_client.websocket_connect("/v1/media/call-x?t=forged"),
    ):
        pass
    assert exc.value.code == 4403


def test_media_socket_single_use(ws_client, monkeypatch):
    async def nothing_pending(_uuid):
        return None  # already claimed, expired, or never dialed

    monkeypatch.setattr(registry, "claim", nothing_pending)
    token = registry.media_token(SETTINGS.secret_key, "call-x")
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        ws_client.websocket_connect(f"/v1/media/call-x?t={token}"),
    ):
        pass
    assert exc.value.code == 4409


def test_media_socket_hands_off_to_the_runner(ws_client, monkeypatch):
    async def pending(_uuid):
        return {"org_uuid": "org-1", "call_id": 5}

    monkeypatch.setattr(registry, "claim", pending)

    from src.application.worker import runner

    ran: list[tuple] = []

    async def fake_run(websocket, *, org_uuid, call_id):
        ran.append((org_uuid, call_id))

    monkeypatch.setattr(runner, "run_media_call", fake_run)

    token = registry.media_token(SETTINGS.secret_key, "call-x")
    with ws_client.websocket_connect(f"/v1/media/call-x?t={token}"):
        pass
    assert ran == [("org-1", 5)]


# ---------------------------------------------------------------------------
# Status webhook — full stack, real DB and redis.
# ---------------------------------------------------------------------------


@pytest.fixture
async def hooks_client():
    transport = httpx.ASGITransport(app=src.main_hooks.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _dialing_call(session, org_uuid: str) -> tuple[int, str]:
    """Returns plain (id, uuid): later expire_all() must not bite attribute access."""
    stack = await seed_stack(session)
    client = await ClientCRUD(session).upsert_by_phone("+15551112222")
    call = await CallCRUD(session).create(
        {
            "client_id": client.id,
            "agent_id": stack.agent.id,
            "direction": CallDirectionEnum.outbound,
            "status": CallLifecycleEnum.calling,
            "attempts_made": 1,
        }
    )
    attempt = await CallAttemptCRUD(session).create(
        {"call_id": call.id, "seq": 1, "status": CallStatusEnum.dialing}
    )
    await session.commit()
    attempt_id, attempt_uuid = attempt.id, str(attempt.uuid)
    await registry.register(
        attempt_uuid, org_uuid=org_uuid, call_id=attempt_id, dial_ttl=60, route_ttl=600
    )
    return attempt_id, attempt_uuid


async def test_status_webhook_requires_token_and_route(hooks_client):
    assert (
        await hooks_client.post("/v1/media/call-x/status?t=forged")
    ).status_code == 403
    token = registry.media_token(SETTINGS.secret_key, "call-x")
    assert (
        await hooks_client.post(f"/v1/media/call-x/status?t={token}", json={})
    ).status_code == 404


async def test_disposition_lands_once_and_stays(hooks_client, session, org_uuid):
    call_id, call_uuid = await _dialing_call(session, org_uuid)
    token = registry.media_token(SETTINGS.secret_key, call_uuid)
    url = f"/v1/media/{call_uuid}/status?t={token}"

    # jambonz vocabulary, JSON body.
    assert (
        await hooks_client.post(url, json={"call_status": "busy"})
    ).status_code == 204
    session.expire_all()
    assert (
        await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == call_id)
    ).status == CallStatusEnum.busy

    # A later, contradictory webhook cannot rewrite a terminal state.
    assert (
        await hooks_client.post(url, json={"call_status": "failed"})
    ).status_code == 204
    session.expire_all()
    assert (
        await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == call_id)
    ).status == CallStatusEnum.busy


async def test_provisional_statuses_are_ignored(hooks_client, session, org_uuid):
    call_id, call_uuid = await _dialing_call(session, org_uuid)
    token = registry.media_token(SETTINGS.secret_key, call_uuid)
    url = f"/v1/media/{call_uuid}/status?t={token}"

    # Twilio vocabulary, form body, provisional value.
    response = await hooks_client.post(url, data={"CallStatus": "ringing"})
    assert response.status_code == 204
    session.expire_all()
    assert (
        await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == call_id)
    ).status == CallStatusEnum.dialing


async def test_final_status_persists_provider_payload(hooks_client, session, org_uuid):
    attempt_id, call_uuid = await _dialing_call(session, org_uuid)
    token = registry.media_token(SETTINGS.secret_key, call_uuid)
    url = f"/v1/media/{call_uuid}/status?t={token}"

    response = await hooks_client.post(
        url,
        json={"call_status": "failed", "sip_status": 486, "sip_reason": "Busy Here"},
    )
    assert response.status_code == 204
    session.expire_all()
    row = await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == attempt_id)
    assert row.status == CallStatusEnum.busy
    assert row.provider_status == "failed"
    assert row.provider_reason == "486 Busy Here"
    assert row.error is None


async def test_failed_status_stores_error_text(hooks_client, session, org_uuid):
    attempt_id, call_uuid = await _dialing_call(session, org_uuid)
    token = registry.media_token(SETTINGS.secret_key, call_uuid)
    url = f"/v1/media/{call_uuid}/status?t={token}"

    # Twilio vocabulary, form body.
    await hooks_client.post(url, data={"CallStatus": "failed", "SipResponseCode": "403"})
    session.expire_all()
    row = await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == attempt_id)
    assert row.status == CallStatusEnum.failed
    assert row.provider_reason == "403"
    assert row.error and "403" in row.error


async def test_unknown_status_fails_with_the_raw_value(hooks_client, session, org_uuid):
    attempt_id, call_uuid = await _dialing_call(session, org_uuid)
    token = registry.media_token(SETTINGS.secret_key, call_uuid)
    url = f"/v1/media/{call_uuid}/status?t={token}"
    await hooks_client.post(url, json={"call_status": "weird"})
    session.expire_all()
    row = await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == attempt_id)
    assert row.status == CallStatusEnum.failed
    assert row.error == "unknown provider status: weird"


async def test_invalid_number_is_not_an_error(hooks_client, session, org_uuid):
    attempt_id, call_uuid = await _dialing_call(session, org_uuid)
    token = registry.media_token(SETTINGS.secret_key, call_uuid)
    await hooks_client.post(
        f"/v1/media/{call_uuid}/status?t={token}",
        json={"call_status": "failed", "sip_status": 404},
    )
    session.expire_all()
    row = await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == attempt_id)
    assert row.status == CallStatusEnum.invalid_number
    assert row.error is None
