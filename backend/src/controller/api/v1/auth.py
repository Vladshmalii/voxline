"""Sign-in, token refresh, sign-out and organization switching.

``public_router`` (login / refresh / logout) works without ``verify_user``;
``router`` (me, organizations, change_organization) sits behind it.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response

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


@public_router.post("/login", response_model=SSessionRead)
async def login(body: SLogin, response: Response, session: ControlSessionDep):
    user = await service.authenticate(session, body.email, body.password)
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
