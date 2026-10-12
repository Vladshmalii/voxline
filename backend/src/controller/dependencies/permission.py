"""Role-based authorization layered on top of ``verify_user``'s authentication.

Roles come from ``src.core.enums``: ``SharedRoleEnum``
(none/admin/super_admin/owner) and ``CallRoleEnum`` (viewer/staff), resolved
per-request via ``get_permission`` (cached in-process and in Redis, backed by
the control database's memberships). ADMIN/SUPER_ADMIN always pass; every
other role is an explicit allow-list per resource below, matching the
product's access matrix.
"""

from typing import Annotated

from fastapi import Depends, WebSocket

from src.core.auth.dependencies import get_permission, verify_user
from src.core.auth.manager import PermissionManager
from src.core.enums import CallRoleEnum, SharedRoleEnum
from src.core.exceptions import Forbidden
from src.core.schemas import PermissionDict, SAuthUser

_FULL_ACCESS = {SharedRoleEnum.ADMIN, SharedRoleEnum.SUPER_ADMIN}

OWNER = SharedRoleEnum.OWNER
STAFF = CallRoleEnum.STAFF
VIEWER = CallRoleEnum.VIEWER


async def _get_role(
    permission: Annotated[PermissionDict, Depends(get_permission)],
) -> str:
    return permission["role"]


#: The acting user's role as request data, not just a 403 gate — for
#: endpoints whose behavior depends on *which* allowed role is calling
#: (VOAD-62's SMS moderation: staff vs owner/admin/super_admin).
CurrentRole = Annotated[str, Depends(_get_role)]


async def is_full_access(role: Annotated[str, Depends(_get_role)]) -> bool:
    """ADMIN/SUPER_ADMIN, for endpoints that mask a field rather than 403 the
    whole resource — e.g. ``Call.uuid`` (VOAD-28/31), owner/staff/viewer keep
    read access to the call but not to its internal uuid.
    """
    return role in _FULL_ACCESS


FullAccessDep = Annotated[bool, Depends(is_full_access)]


def require_role(*roles: SharedRoleEnum | CallRoleEnum):
    """Allow ADMIN/SUPER_ADMIN plus any role listed here; 403 otherwise.

    No roles at all means "ADMIN/SUPER_ADMIN only" — used for resources the
    rest of the access matrix excludes everyone else from (Telephony,
    Messaging, Admin Stats, writing Models).
    """
    allowed = set(roles)

    async def _check(role: Annotated[str, Depends(_get_role)]) -> None:
        if role not in _FULL_ACCESS and role not in allowed:
            raise Forbidden

    return Depends(_check)


async def _get_role_ws(
    websocket: WebSocket, _: Annotated[None, Depends(verify_user)]
) -> str:
    # Mirrors get_current_user_ws (src/controller/dependencies/auth.py):
    # get_permission is Request-typed and can't be injected on a WS route,
    # so this re-reads the user verify_user already stashed on connection
    # state and asks PermissionManager directly.
    user: SAuthUser = websocket.state.user
    permission = await PermissionManager.get_permission(user.organization_uuid, user.id)
    return permission["role"]


def require_role_ws(*roles: SharedRoleEnum | CallRoleEnum):
    """WebSocket-route equivalent of ``require_role``."""
    allowed = set(roles)

    async def _check(role: Annotated[str, Depends(_get_role_ws)]) -> None:
        if role not in _FULL_ACCESS and role not in allowed:
            raise Forbidden

    return Depends(_check)


# ── resource access ──────────────────────────────────────────────────────────
admin_only = (
    require_role()
)  # ADMIN/SUPER_ADMIN only: Telephony, Messaging, Admin Stats, Model writes

view_dashboard = require_role(OWNER, STAFF, VIEWER)  # stats + services_status

view_calls = require_role(OWNER, STAFF, VIEWER)
write_calls = require_role(OWNER, STAFF)  # originate, cancel, tags

view_campaigns = require_role(OWNER, STAFF, VIEWER)
write_campaigns = require_role(OWNER, STAFF)  # CRUD, uploads, lifecycle

view_audiences = require_role(
    OWNER, STAFF, VIEWER
)  # also clients.py — same lead-data tier
write_audiences = require_role(OWNER, STAFF)  # CRUD, CSV, client edits/import

view_agents = require_role(OWNER, STAFF, VIEWER)
voice_preview_agents = require_role(
    OWNER, STAFF
)  # preview-voice(-direct), playground WS
write_agents = require_role(OWNER, STAFF)  # create/update agent + languages (VOAD-57)
delete_agents = require_role(OWNER)  # delete agent/language stays owner-only
sms_moderation = require_role(
    OWNER
)  # approve/reject agent SMS text (VOAD-62) — staff excluded


def requires_sms_moderation(role: str) -> bool:
    """VOAD-62: only staff-authored/edited SMS-tool text needs sign-off —
    owner/admin/super_admin write approved text directly."""
    return role == STAFF


view_models = require_role(
    OWNER, STAFF, VIEWER
)  # write is admin_only — owner doesn't get it here

providers_access = (
    admin_only  # Endpoint/credentials changes can reroute assigned models.
)

view_sms = require_role(OWNER, STAFF, VIEWER)
write_sms = require_role(OWNER, STAFF)  # sending

view_billing = require_role(OWNER, STAFF, VIEWER)
write_billing = require_role(OWNER)  # topup, tariffs
