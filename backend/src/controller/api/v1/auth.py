"""Sign-in, token refresh, sign-out and organization switching.

``public_router`` (login / refresh / logout) works without ``verify_user``;
``router`` (me, organizations, change_organization) sits behind it.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from loguru import logger

from src.controller.dependencies.control import ControlSessionDep, CurrentDbUser
from src.core.auth.cookies import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from src.core.auth.dependencies import get_current_user
from src.core.auth.manager import PermissionManager
from src.core.control import service
from src.core.control.models import Organization, User
from src.core.exceptions import Forbidden, Unauthorized
from src.core.redis import RedisBase
from src.core.schemas import SAuthUser
from src.schemas.auth import (
    SAuthOrganizationRead,
    SAuthUserRead,
    SLogin,
    SOrganizationRoleRead,
    SSessionRead,
)

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(tags=["auth"])


def _session_body(user: User, org: Organization, role: str) -> SSessionRead:
    return SSessionRead(
        user=SAuthUserRead(
            id=user.id,
            email=user.email,
            name=user.name,
            is_superuser=user.is_superuser,
        ),
        organization=SAuthOrganizationRead(uuid=str(org.uuid), name=org.name),
        role=role,
    )


#: Failed sign-ins allowed per window, per e-mail and per client address.
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_PER_EMAIL = 10
_LOGIN_MAX_PER_IP = 50


async def _login_keys(request: Request, email: str) -> list[tuple[str, int]]:
    ip = request.client.host if request.client else "unknown"
    return [
        (f"login:fail:email:{service.normalize_email(email)}", _LOGIN_MAX_PER_EMAIL),
        (f"login:fail:ip:{ip}", _LOGIN_MAX_PER_IP),
    ]


async def _login_blocked(keys: list[tuple[str, int]]) -> bool:
    try:
        client = await RedisBase.get_client()
        counts = await client.mget([key for key, _ in keys])
    except Exception as exc:  # noqa: BLE001 - throttling must not take sign-in down
        logger.warning(f"login throttle unavailable: {exc}")
        return False
    return any(int(c or 0) >= limit for c, (_, limit) in zip(counts, keys))


async def _login_failed(keys: list[tuple[str, int]]) -> None:
    try:
        client = await RedisBase.get_client()
        for key, _ in keys:
            if await client.incr(key) == 1:
                await client.expire(key, _LOGIN_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"login throttle unavailable: {exc}")


@public_router.post("/login", response_model=SSessionRead)
async def login(
    body: SLogin, request: Request, response: Response, session: ControlSessionDep
):
    keys = await _login_keys(request, body.email)
    if await _login_blocked(keys):
        raise HTTPException(status_code=429, detail="too_many_attempts")
    try:
        user = await service.authenticate(session, body.email, body.password)
    except Unauthorized:
        await _login_failed(keys)
        raise
    org, role = await service.resolve_login_org(session, user, body.organization_uuid)
    access, refresh = await service.issue_tokens(session, user, org)
    set_auth_cookies(response, access, refresh)
    return _session_body(user, org, role)


@public_router.post("/refresh", response_model=SSessionRead)
async def refresh(
    response: Response,
    session: ControlSessionDep,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
):
    if not refresh_token:
        raise Unauthorized
    user, org, role, access, new_refresh = await service.rotate_refresh(
        session, refresh_token
    )
    set_auth_cookies(response, access, new_refresh)
    return _session_body(user, org, role)


@public_router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session: ControlSessionDep,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
):
    await service.revoke_refresh(session, refresh_token)
    clear_auth_cookies(response)


@router.get("/auth/me", response_model=SSessionRead)
async def me(
    caller: Annotated[SAuthUser, Depends(get_current_user)],
    user: CurrentDbUser,
    session: ControlSessionDep,
):
    org = await service.get_org(session, caller.organization_uuid)
    if org is None or not org.is_active:
        raise Forbidden
    # Resolved through the cache so ``me`` and the permission gates agree.
    permission = await PermissionManager.get_permission(
        caller.organization_uuid, user.id
    )
    return _session_body(user, org, permission["role"])


@router.get("/organizations", response_model=list[SOrganizationRoleRead])
async def list_my_organizations(user: CurrentDbUser, session: ControlSessionDep):
    return [
        SOrganizationRoleRead(uuid=str(org.uuid), name=org.name, role=role)
        for org, role in await service.user_organizations(session, user)
    ]


@router.post("/auth/change_organization/{org_uuid}", response_model=SSessionRead)
async def change_organization(
    org_uuid: str,
    response: Response,
    user: CurrentDbUser,
    session: ControlSessionDep,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
):
    org, role = await service.resolve_login_org(session, user, org_uuid)
    await service.revoke_refresh(session, refresh_token)
    access, new_refresh = await service.issue_tokens(session, user, org)
    set_auth_cookies(response, access, new_refresh)
    return _session_body(user, org, role)
