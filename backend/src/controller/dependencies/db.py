from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Path

from src.core.auth.dependencies import get_current_user
from src.core.db.session import AsyncSession, SessionMaker
from src.core.schemas import SAuthUser


def make_session_dep(org_uuid_dep):
    async def _get_session(
        org_uuid: Annotated[str, Depends(org_uuid_dep)],
    ) -> AsyncGenerator[AsyncSession]:
        """Yield a read-only session (no auto-commit)."""
        async with SessionMaker.get_session(org_uuid)() as session:
            yield session

    return Annotated[AsyncSession, Depends(_get_session)]


def make_session_commit_dep(org_uuid_dep):
    async def _get_session_commit(
        org_uuid: Annotated[str, Depends(org_uuid_dep)],
    ) -> AsyncGenerator[AsyncSession]:
        """Yield a session that auto-commits on success and rolls back on error."""
        async with SessionMaker.get_session(org_uuid)() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return Annotated[AsyncSession, Depends(_get_session_commit)]


async def extract_org_uuid_from_path(org_uuid: Annotated[str, Path()]) -> str:
    return org_uuid


async def extract_org_uuid_from_user(
    user: Annotated[SAuthUser, Depends(get_current_user)],
) -> str:
    return user.organization_uuid


#: The caller's organization, for the rare route that needs the identifier
#: itself and not just a session bound to it (an SMS whose delivery
#: callback must be routable back to this database later).
OrgUuidDep = Annotated[str, Depends(extract_org_uuid_from_user)]

SessionPathDep = make_session_dep(extract_org_uuid_from_path)
SessionCommitPathDep = make_session_commit_dep(extract_org_uuid_from_path)
SessionUserDep = make_session_dep(extract_org_uuid_from_user)
SessionUserCommitDep = make_session_commit_dep(extract_org_uuid_from_user)
