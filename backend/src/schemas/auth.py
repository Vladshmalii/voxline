"""Request/response models for the auth and account-management API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SLogin(BaseModel):
    email: str
    password: str
    organization_uuid: str | None = None


class SAuthUserRead(BaseModel):
    id: int
    email: str
    name: str
    is_superuser: bool


class SAuthOrganizationRead(BaseModel):
    uuid: str
    name: str


class SSessionRead(BaseModel):
    """What login / refresh / me / change_organization answer with."""

    user: SAuthUserRead
    organization: SAuthOrganizationRead
    role: str


class SOrganizationRoleRead(BaseModel):
    uuid: str
    name: str
    role: str


# -- admin --------------------------------------------------------------------


class SOrganizationAdminRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    name: str
    is_active: bool
    created_at: datetime


class SOrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SMembershipRead(BaseModel):
    organization_uuid: str
    organization_name: str
    role: str


class SUserAdminRead(BaseModel):
    id: int
    email: str
    name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    memberships: list[SMembershipRead]


class SUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=255)
    password: str = Field(min_length=8, max_length=256)
    is_superuser: bool = False
    #: Defaults to the caller's current organization.
    organization_uuid: str | None = None
    role: str = "staff"


class SUserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    is_active: bool | None = None
    is_superuser: bool | None = None


class SMemberRoleSet(BaseModel):
    role: str


class SMemberRead(BaseModel):
    user_id: int
    organization_uuid: str
    role: str
