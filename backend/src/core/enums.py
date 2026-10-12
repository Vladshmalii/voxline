from enum import StrEnum
from typing import Union


class SharedRoleEnum(StrEnum):
    NONE = "none"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    OWNER = "owner"


class CallRoleEnum(StrEnum):
    VIEWER = "viewer"
    STAFF = "staff"


PermissionRoleEnum = Union[SharedRoleEnum, CallRoleEnum]

#: Every role string a membership may hold.
ALL_ROLES: frozenset[str] = frozenset(
    {*(r.value for r in SharedRoleEnum), *(r.value for r in CallRoleEnum)}
)
