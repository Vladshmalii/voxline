"""Playground WS: auth at the handshake, org scoping, and the service seam.

Admission tests run through starlette's TestClient (its own event loop, so
the service is faked at the module seam — same approach as the media gateway
tests); the unknown-agent path exercises the real service against the real
scratch database using a fake socket, in the fixture loop.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src.controller.dependencies.auth import get_current_user_ws
from src.core.schemas import SAuthUser


@pytest.fixture
def ws_client(app, org_uuid):
    app.dependency_overrides[get_current_user_ws] = lambda: SAuthUser(
        id=1, organization_uuid=org_uuid
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user_ws, None)


def test_playground_hands_off_with_org_scope(ws_client, org_uuid, monkeypatch):
    """The route's whole job: authenticated user's org + agent id + language."""
    from src.application.services import playground as service

    ran: list[dict] = []

    async def fake_run(websocket, *, org_uuid, agent_id, language=None):
        await websocket.accept()
        ran.append({"org": org_uuid, "agent": agent_id, "language": language})

    monkeypatch.setattr(service, "run_playground", fake_run)

    with ws_client.websocket_connect("/v1/voice-agents/7/playground?language=de"):
        pass
    assert ran == [{"org": org_uuid, "agent": 7, "language": "de"}]


async def test_unknown_agent_closes_4404(org_uuid):
    """Real service, real scratch DB: an agent id from another world closes."""
    from src.application.services.playground import run_playground

    class FakeWebsocket:
        closed_with: int | None = None

        async def close(self, code: int = 1000) -> None:
            self.closed_with = code

        async def accept(self) -> None:  # pragma: no cover - must not be reached
            raise AssertionError("accepted a socket for a missing agent")

    websocket = FakeWebsocket()
    await run_playground(websocket, org_uuid=org_uuid, agent_id=99999)
    assert websocket.closed_with == 4404
