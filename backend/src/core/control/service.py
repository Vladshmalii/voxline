"""Control-database operations: users, organizations, memberships, sessions.

Functions take an ``AsyncSession`` on the control database and never commit:
the caller (the request dependency or the bootstrap CLI) owns the transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import security
from src.core.config import Config
from src.core.control.models import Membership, Organization, RefreshToken, User
from src.core.enums import ALL_ROLES, SharedRoleEnum
from src.core.exceptions import BadRequest, Conflict, Forbidden, NotFound, Unauthorized


def normalize_email(email: str) -> str:
    return email.strip().lower()


def parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise NotFound from None


# -- lookups ------------------------------------------------------------------


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(select(User).where(User.email == normalize_email(email)))
    ).scalar_one_or_none()


async def get_org(session: AsyncSession, org_uuid: str) -> Organization | None:
    return (
        await session.execute(
            select(Organization).where(Organization.uuid == parse_uuid(org_uuid))
        )
    ).scalar_one_or_none()


async def get_membership(
    session: AsyncSession, user_id: int, organization_id: int
) -> Membership | None:
    return (
        await session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()


async def role_for(session: AsyncSession, user: User, org: Organization) -> str | None:
    """The user's effective role in the organization, or None if no access."""
    if user.is_superuser:
        return SharedRoleEnum.SUPER_ADMIN.value
    membership = await get_membership(session, user.id, org.id)
    return membership.role if membership is not None else None


async def user_organizations(
    session: AsyncSession, user: User
) -> list[tuple[Organization, str]]:
    """Active organizations the user can enter, each with their role there."""
    if user.is_superuser:
        orgs = (
            (
                await session.execute(
                    select(Organization)
                    .where(Organization.is_active.is_(True))
                    .order_by(Organization.id)
                )
            )
            .scalars()
            .all()
        )
        return [(o, SharedRoleEnum.SUPER_ADMIN.value) for o in orgs]
    rows = (
        await session.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id, Organization.is_active.is_(True))
            .order_by(Membership.id)
        )
    ).all()
    return [(o, role) for o, role in rows]


async def permission_role(session: AsyncSession, org_uuid: str, user_id: int) -> str:
    """Role of ``user_id`` in the organization; ``Forbidden`` if none."""
    user = await get_user(session, user_id)
    if user is None or not user.is_active:
        raise Forbidden
    org = await get_org(session, org_uuid)
    if org is None or not org.is_active:
        raise Forbidden
    role = await role_for(session, user, org)
    if role is None:
        raise Forbidden
    return role


# -- authentication -----------------------------------------------------------

#: Verified against when the e-mail is unknown, so a miss costs the same as a
#: wrong password.
_DUMMY_HASH = security.hash_password("voxline-dummy-password")


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    if user is None:
        await security.verify_password(_DUMMY_HASH, password)
        raise Unauthorized("invalid_credentials")
    ok = await security.verify_password(user.password_hash, password)
    if not ok or not user.is_active:
        raise Unauthorized("invalid_credentials")
    return user


async def resolve_login_org(
    session: AsyncSession, user: User, org_uuid: str | None
) -> tuple[Organization, str]:
    if org_uuid:
        org = await get_org(session, org_uuid)
        if org is None or not org.is_active:
            raise Forbidden
        role = await role_for(session, user, org)
        if role is None:
            raise Forbidden
        return org, role
    orgs = await user_organizations(session, user)
    if not orgs:
        raise Forbidden("no_organization")
    return orgs[0]


async def issue_tokens(
    session: AsyncSession, user: User, org: Organization
) -> tuple[str, str]:
    """Mint an access JWT and persist a fresh refresh token. Returns both."""
    raw, token_hash = security.new_refresh_token()
    session.add(
        RefreshToken(
            token_hash=token_hash,
            user_id=user.id,
            organization_id=org.id,
            expires_at=datetime.now() + timedelta(days=Config.jwt.refresh_ttl_days),
        )
    )
    await session.flush()
    return security.create_access_token(user.id, str(org.uuid)), raw


async def rotate_refresh(
    session: AsyncSession, raw: str
) -> tuple[User, Organization, str, str, str]:
    """Consume a refresh token and issue the next pair.

    Returns ``(user, organization, role, access_token, new_refresh_token)``.
    Presenting an already-revoked token revokes every live token of that user
    (replay of a rotated token) and fails.
    """
    row = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == security.hash_refresh_token(raw))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise Unauthorized
    now = datetime.now()
    if row.revoked_at is not None:
        await revoke_user_tokens(session, row.user_id)
        # The failure below rolls the request back unless committed first.
        await session.commit()
        raise Unauthorized
    if row.expires_at <= now:
        raise Unauthorized
    user = await get_user(session, row.user_id)
    org = await session.get(Organization, row.organization_id)
    if user is None or not user.is_active or org is None or not org.is_active:
        raise Unauthorized
    role = await role_for(session, user, org)
    if role is None:
        raise Unauthorized
    row.revoked_at = now
    access, refresh = await issue_tokens(session, user, org)
    return user, org, role, access, refresh


async def revoke_refresh(session: AsyncSession, raw: str | None) -> None:
    if not raw:
        return
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == security.hash_refresh_token(raw),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now())
    )


async def revoke_user_tokens(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now())
    )


# -- management ---------------------------------------------------------------


def validate_role(role: str) -> str:
    if role not in ALL_ROLES:
        raise BadRequest("invalid_role")
    return role


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    name: str = "",
    is_superuser: bool = False,
    is_active: bool = True,
) -> User:
    email = normalize_email(email)
    if await get_user_by_email(session, email) is not None:
        raise Conflict("email_taken")
    user = User(
        email=email,
        name=name,
        password_hash=await security.hash_password_async(password),
        is_superuser=is_superuser,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user, ["memberships"])
    return user


async def create_organization(
    session: AsyncSession, name: str, org_uuid: UUID | None = None
) -> Organization:
    org = Organization(name=name.strip(), uuid=org_uuid or uuid4())
    session.add(org)
    await session.flush()
    return org


async def set_membership(
    session: AsyncSession, user_id: int, organization_id: int, role: str
) -> Membership:
    validate_role(role)
    membership = await get_membership(session, user_id, organization_id)
    if membership is None:
        membership = Membership(
            user_id=user_id, organization_id=organization_id, role=role
        )
        session.add(membership)
    else:
        membership.role = role
    await session.flush()
    return membership


async def remove_membership(
    session: AsyncSession, user_id: int, organization_id: int
) -> bool:
    membership = await get_membership(session, user_id, organization_id)
    if membership is None:
        return False
    await session.delete(membership)
    await session.flush()
    return True


async def revoke_user_org_tokens(
    session: AsyncSession, user_id: int, organization_id: int
) -> None:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.organization_id == organization_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now())
    )
