"""Playground WebSocket — talk to an agent from the admin UI, no telephony.

Lives on the *app*, not the hooks service, because it is an operator surface:
authentication is the platform's user cookie (``verify_user`` runs during the
WS handshake; a bad cookie is rejected before the upgrade), and the org scope
comes from the authenticated user — an operator can only play with their own
organization's agents.

The pipeline stack is imported lazily inside the route, so the admin app
still boots without pipecat; the first playground session pays the load.
Wire contract for the browser client is documented on
:mod:`src.application.services.playground`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket

from src.controller.dependencies.auth import get_current_user_ws
from src.controller.dependencies.permission import OWNER, STAFF, require_role_ws
from src.core.schemas import SAuthUser

router = APIRouter(tags=["playground"])


@router.websocket(
    "/voice-agents/{item_id}/playground",
    dependencies=[require_role_ws(OWNER, STAFF)],
)
async def playground(
    websocket: WebSocket,
    item_id: int,
    user: Annotated[SAuthUser, Depends(get_current_user_ws)],
    language: str | None = None,
) -> None:
    """One conversation with the agent, exactly as a caller would have it."""
    from src.application.services import playground as service

    await service.run_playground(
        websocket,
        org_uuid=user.organization_uuid,
        agent_id=item_id,
        language=language,
    )
