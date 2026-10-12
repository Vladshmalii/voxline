"""FastAPI auth dependencies: cookie -> user -> role."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends
from fastapi.requests import HTTPConnection

from src.core.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from src.core.auth.manager import PermissionManager
from src.core.auth.security import decode_user_token
from src.core.enums import PermissionRoleEnum, SharedRoleEnum
from src.core.exceptions import Forbidden, TokenExpired, Unauthorized
from src.core.schemas import PermissionDict, SAuthUser

FULL_ACCESS_ROLES = frozenset({SharedRoleEnum.ADMIN, SharedRoleEnum.SUPER_ADMIN})


async def verify_user(
    request: HTTPConnection,
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> None:
    """Authenticate the request from the ``access_token`` cookie.

    ``token_expired`` (401) tells the frontend to call ``/v1/auth/refresh``; it
    is also what a missing access cookie turns into while a refresh cookie is
    still present. Anything else is ``unauthorized`` (or a ``token_*`` detail).
    """
    if access_token is None:
        raise TokenExpired if refresh_token else Unauthorized
    request.state.user = decode_user_token(access_token)


# HTTPConnection, not Request: the same dependency then resolves on WebSocket
# routes, where a Request-typed parameter can't be injected.
async def get_current_user(
    request: HTTPConnection, _: Annotated[None, Depends(verify_user)]
) -> SAuthUser:
    return request.state.user


async def get_permission(
    user: Annotated[SAuthUser, Depends(get_current_user)],
) -> PermissionDict:
    return await PermissionManager.get_permission(user.organization_uuid, user.id)


def get_role(permission: PermissionDict) -> str | None:
    return permission.get("role")


def verify_permission(*permissions: PermissionRoleEnum):
    """Allow ADMIN/SUPER_ADMIN plus any role listed here; 403 otherwise."""
    allowed = frozenset(permissions)

    async def _verify_permission(
        permission: Annotated[PermissionDict, Depends(get_permission)],
    ) -> None:
        role = get_role(permission)
        if role not in FULL_ACCESS_ROLES and role not in allowed:
            raise Forbidden

    return Annotated[None, Depends(_verify_permission)]
