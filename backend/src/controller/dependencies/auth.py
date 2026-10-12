"""WebSocket-compatible auth for the admin app.

``verify_user`` takes the common ``HTTPConnection`` and stores the decoded user
on connection state, so a WS route only needs this thin reader on top of it. A
missing/bad cookie rejects the socket during the HTTP handshake, before any
upgrade.
"""

from typing import Annotated

from fastapi import Depends, WebSocket

from src.core.auth.dependencies import verify_user
from src.core.schemas import SAuthUser


async def get_current_user_ws(
    websocket: WebSocket, _: Annotated[None, Depends(verify_user)]
) -> SAuthUser:
    return websocket.state.user
