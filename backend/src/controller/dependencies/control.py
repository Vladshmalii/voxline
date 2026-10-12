"""Control-database dependencies: a request session plus the admin gates."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth.dependencies import (
    FULL_ACCESS_ROLES,
    get_current_user,
    get_permission,
)
from src.core.control import service
from src.core.control.models import User
from src.core.db.session import SessionMaker
from src.core.exceptions import Forbidden, Unauthorized
from src.core.schemas import PermissionDict, SAuthUser


async def _control_session() -> AsyncGenerator[AsyncSession]:
    """Control-database session that commits on success, rolls back on error."""
    async with SessionMaker.get_control_session()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


ControlSessionDep = Annotated[AsyncSession, Depends(_control_session)]


async def _current_db_user(
    user: Annotated[SAuthUser, Depends(get_current_user)],
    session: ControlSessionDep,
) -> User:
    db_user = await service.get_user(session, user.id)
    if db_user is None or not db_user.is_active:
        raise Unauthorized
    return db_user


CurrentDbUser = Annotated[User, Depends(_current_db_user)]


async def _require_superuser(user: CurrentDbUser) -> User:
    if not user.is_superuser:
        raise Forbidden
    return user


SuperuserDep = Annotated[User, Depends(_require_superuser)]


async def _require_admin(
    user: CurrentDbUser,
    permission: Annotated[PermissionDict, Depends(get_permission)],
) -> User:
    """Admin or super_admin in the organization the token is bound to."""
    if permission["role"] not in FULL_ACCESS_ROLES:
        raise Forbidden
    return user


AdminDep = Annotated[User, Depends(_require_admin)]


async def ensure_org_admin(session: AsyncSession, caller: User, org) -> None:
    """The caller may manage ``org``: a superuser, or its admin/super_admin."""
    role = await service.role_for(session, caller, org)
    if role not in FULL_ACCESS_ROLES:
        raise Forbidden
