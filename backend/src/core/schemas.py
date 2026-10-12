from typing import TypedDict

from pydantic import BaseModel


class SAuthUser(BaseModel):
    """The authenticated caller, as carried in the access token."""

    id: int
    organization_uuid: str


class PermissionDict(TypedDict):
    role: str
