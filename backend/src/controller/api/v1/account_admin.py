"""Account management: organizations, users and memberships.

Every route needs admin / super_admin in the organization the token is bound
to (``AdminDep``). Creating organizations, and granting the superuser flag or
the ``super_admin`` role, is superuser-only; everything else an org admin may
do only inside organizations they administer.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from src.controller.dependencies.control import (
    AdminDep,
    ControlSessionDep,
    SuperuserDep,
    ensure_org_admin,
)
from src.core.auth import security
from src.core.auth.dependencies import FULL_ACCESS_ROLES, get_current_user
from src.core.auth.manager import PermissionManager
from src.core.control import service
from src.core.control.models import Membership, Organization, User
from src.core.enums import SharedRoleEnum
from src.core.exceptions import BadRequest, Forbidden, NotFound
from src.core.schemas import SAuthUser
from src.schemas.auth import (
    SMemberRead,
    SMemberRoleSet,
    SMembershipRead,
    SOrganizationAdminRead,
    SOrganizationCreate,
    SUserAdminRead,
    SUserCreate,
    SUserUpdate,
)
from src.sync_db import drop_organization_database, provision_organization

router = APIRouter(prefix="/admin", tags=["account-admin"])


async def _administered_org_ids(session, caller: User) -> set[int] | None:
    """Organization ids the caller manages; None means every organization."""
    if caller.is_superuser:
        return None
    rows = await session.execute(
        select(Membership.organization_id).where(
            Membership.user_id == caller.id,
            Membership.role.in_([r.value for r in FULL_ACCESS_ROLES]),
        )
    )
    return set(rows.scalars().all())


def _user_read(user: User, visible_org_ids: set[int] | None) -> SUserAdminRead:
    return SUserAdminRead(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        memberships=[
            SMembershipRead(
                organization_uuid=str(m.organization.uuid),
                organization_name=m.organization.name,
                role=m.role,
            )
            for m in user.memberships
            if visible_org_ids is None or m.organization_id in visible_org_ids
        ],
    )


async def _org_or_404(session, org_uuid: str) -> Organization:
    org = await service.get_org(session, org_uuid)
    if org is None:
        raise NotFound
    return org


def _check_assignable(caller: User, role: str) -> None:
    service.validate_role(role)
    if role == SharedRoleEnum.SUPER_ADMIN and not caller.is_superuser:
        raise Forbidden


# -- organizations ------------------------------------------------------------


@router.get("/organizations", response_model=list[SOrganizationAdminRead])
async def list_organizations(caller: AdminDep, session: ControlSessionDep):
    stmt = select(Organization).order_by(Organization.id)
    ids = await _administered_org_ids(session, caller)
    if ids is not None:
        stmt = stmt.where(Organization.id.in_(ids))
    return (await session.execute(stmt)).scalars().all()


@router.post("/organizations", response_model=SOrganizationAdminRead, status_code=201)
async def create_organization(
    body: SOrganizationCreate, caller: SuperuserDep, session: ControlSessionDep
):
    """Create the organization and its tenant database (migrated to head)."""
    org = await service.create_organization(session, body.name)
    try:
        await provision_organization(str(org.uuid))
    except Exception:
        # Nothing refers to the database yet; do not leave a half-made tenant.
        await session.rollback()
        drop_organization_database(str(org.uuid))
        raise
    return org


# -- users --------------------------------------------------------------------


@router.get("/users", response_model=list[SUserAdminRead])
async def list_users(
    caller: AdminDep,
    session: ControlSessionDep,
    organization_uuid: str | None = Query(default=None),
):
    """Superusers see every user; org admins see members of their organizations."""
    ids = await _administered_org_ids(session, caller)
    stmt = select(User).order_by(User.id)
    if organization_uuid is not None:
        org = await _org_or_404(session, organization_uuid)
        await ensure_org_admin(session, caller, org)
        stmt = stmt.where(
            User.id.in_(
                select(Membership.user_id).where(Membership.organization_id == org.id)
            )
        )
    elif ids is not None:
        stmt = stmt.where(
            User.id.in_(
                select(Membership.user_id).where(Membership.organization_id.in_(ids))
            )
        )
    users = (await session.execute(stmt)).scalars().unique().all()
    return [_user_read(u, ids) for u in users]


@router.post("/users", response_model=SUserAdminRead, status_code=201)
async def create_user(
    body: SUserCreate,
    caller: AdminDep,
    session: ControlSessionDep,
    current: Annotated[SAuthUser, Depends(get_current_user)],
):
    if body.is_superuser and not caller.is_superuser:
        raise Forbidden
    org = None
    # Default: the organization the caller is working in. A new superuser needs
    # no membership (they are super_admin everywhere).
    org_uuid = body.organization_uuid
    if org_uuid is None and not body.is_superuser:
        org_uuid = current.organization_uuid
    if org_uuid is not None:
        org = await _org_or_404(session, org_uuid)
        await ensure_org_admin(session, caller, org)
        _check_assignable(caller, body.role)
    user = await service.create_user(
        session,
        email=body.email,
        password=body.password,
        name=body.name,
        is_superuser=body.is_superuser,
    )
    if org is not None:
        await service.set_membership(session, user.id, org.id, body.role)
        await session.refresh(user, ["memberships"])
    return _user_read(user, await _administered_org_ids(session, caller))


@router.patch("/users/{user_id}", response_model=SUserAdminRead)
async def update_user(
    user_id: int, body: SUserUpdate, caller: AdminDep, session: ControlSessionDep
):
    user = await service.get_user(session, user_id)
    if user is None:
        raise NotFound
    ids = await _administered_org_ids(session, caller)
    if ids is not None:
        # An org admin touches only non-superusers who belong to their orgs.
        shared = any(m.organization_id in ids for m in user.memberships)
        if user.is_superuser or not shared or body.is_superuser is not None:
            raise Forbidden
    if user.id == caller.id and body.is_active is False:
        raise BadRequest("cannot_deactivate_self")
    if body.name is not None:
        user.name = body.name
    if body.is_superuser is not None:
        user.is_superuser = body.is_superuser
    if body.is_active is not None:
        user.is_active = body.is_active
    revoke = body.is_active is False or body.password is not None
    if body.password is not None:
        user.password_hash = await security.hash_password_async(body.password)
    if revoke:
        await service.revoke_user_tokens(session, user.id)
    await session.flush()
    # The role cache must not outlive a deactivation / superuser change.
    await session.commit()
    await PermissionManager.invalidate_user(user.id)
    return _user_read(user, ids)


# -- memberships --------------------------------------------------------------


@router.put("/organizations/{org_uuid}/members/{user_id}", response_model=SMemberRead)
async def set_member_role(
    org_uuid: str,
    user_id: int,
    body: SMemberRoleSet,
    caller: AdminDep,
    session: ControlSessionDep,
):
    """Add the user to the organization, or change their role in it."""
    org = await _org_or_404(session, org_uuid)
    await ensure_org_admin(session, caller, org)
    _check_assignable(caller, body.role)
    if await service.get_user(session, user_id) is None:
        raise NotFound
    membership = await service.set_membership(session, user_id, org.id, body.role)
    await session.commit()
    await PermissionManager.invalidate(str(org.uuid), user_id)
    return SMemberRead(
        user_id=user_id, organization_uuid=str(org.uuid), role=membership.role
    )


@router.delete("/organizations/{org_uuid}/members/{user_id}", status_code=204)
async def remove_member(
    org_uuid: str, user_id: int, caller: AdminDep, session: ControlSessionDep
):
    org = await _org_or_404(session, org_uuid)
    await ensure_org_admin(session, caller, org)
    if user_id == caller.id:
        raise BadRequest("cannot_remove_self")
    if not await service.remove_membership(session, user_id, org.id):
        raise NotFound
    await service.revoke_user_org_tokens(session, user_id, org.id)
    await session.commit()
    await PermissionManager.invalidate(str(org.uuid), user_id)
    return Response(status_code=204)
