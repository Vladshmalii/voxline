"""The caller's own role for this service.

No gate beyond the router-wide ``verify_user``: a role of ``none`` is a
valid, expected answer here — an authenticated user this service simply
hasn't been granted anything for — not something to 403 on. The frontend
uses this to decide what to show, mirroring the access matrix enforced by
``src.controller.dependencies.permission`` rather than duplicating it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.controller.dependencies.db import SessionUserDep
from src.core.auth.dependencies import get_permission
from src.core.enums import SharedRoleEnum
from src.core.schemas import PermissionDict
from src.repositories.billing import OrganizationBalanceCRUD

router = APIRouter(prefix="/me", tags=["me"])


class SMyRole(BaseModel):
    role: str
    #: False for per-minute clients (billing closed to non-admins).
    billing_enabled: bool = True


@router.get("", response_model=SMyRole)
async def get_my_role(
    permission: Annotated[PermissionDict, Depends(get_permission)],
    session: SessionUserDep,
):
    role = permission["role"]
    full_access = role in (SharedRoleEnum.ADMIN, SharedRoleEnum.SUPER_ADMIN)
    # A role of ``none`` may have no balance row to read — nothing to hide then.
    minutes_only = (
        False
        if role == SharedRoleEnum.NONE
        else (await OrganizationBalanceCRUD(session).get_or_create()).minutes_only
    )
    return SMyRole(role=role, billing_enabled=full_access or not minutes_only)
