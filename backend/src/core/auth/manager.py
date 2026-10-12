"""Role resolution with a two-level cache: in-process, then Redis, then the DB."""

from __future__ import annotations

import time

from loguru import logger

from src.core.control import service
from src.core.db.session import SessionMaker
from src.core.redis import PermissionCache
from src.core.schemas import PermissionDict

PERMISSION_TTL_SECONDS = 60
_MAX_ENTRIES = 5000

_local: dict[tuple[str, int], tuple[PermissionDict, float]] = {}


def _local_get(key: tuple[str, int]) -> PermissionDict | None:
    entry = _local.get(key)
    if entry is None:
        return None
    value, exp = entry
    if exp > time.monotonic():
        return value
    _local.pop(key, None)
    return None


def _local_set(key: tuple[str, int], value: PermissionDict) -> None:
    if len(_local) >= _MAX_ENTRIES:
        now = time.monotonic()
        for k in [k for k, (_, exp) in _local.items() if exp < now] or list(_local)[
            :100
        ]:
            _local.pop(k, None)
    _local[key] = (value, time.monotonic() + PERMISSION_TTL_SECONDS)


class PermissionManager:
    @classmethod
    async def get_permission(
        cls, organization_uuid: str, user_id: int
    ) -> PermissionDict:
        key = (organization_uuid, user_id)
        cached = _local_get(key)
        if cached is not None:
            return cached

        try:
            shared = await PermissionCache.get(organization_uuid, user_id)
        except Exception as exc:  # noqa: BLE001 - Redis is an optimisation here
            logger.warning(f"permission cache read failed: {exc}")
            shared = None
        if shared is not None:
            _local_set(key, shared)
            return shared

        async with SessionMaker.get_control_session()() as session:
            role = await service.permission_role(session, organization_uuid, user_id)
        permission: PermissionDict = {"role": role}
        _local_set(key, permission)
        try:
            await PermissionCache.set(
                organization_uuid, user_id, permission, expire=PERMISSION_TTL_SECONDS
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"permission cache write failed: {exc}")
        return permission

    @classmethod
    async def invalidate(cls, organization_uuid: str, user_id: int) -> None:
        """Drop one cached role (this process now, other processes within the TTL)."""
        _local.pop((organization_uuid, user_id), None)
        try:
            await PermissionCache.delete_many(organization_uuid, [user_id])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"permission cache invalidation failed: {exc}")

    @classmethod
    async def invalidate_user(cls, user_id: int) -> None:
        """Drop a user's cached role in every organization."""
        from sqlalchemy import select

        from src.core.control.models import Membership, Organization

        async with SessionMaker.get_control_session()() as session:
            uuids = (
                (
                    await session.execute(
                        select(Organization.uuid)
                        .join(Membership, Membership.organization_id == Organization.id)
                        .where(Membership.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
        for org_uuid in uuids:
            await cls.invalidate(str(org_uuid), user_id)
        for key in [k for k in _local if k[1] == user_id]:
            _local.pop(key, None)

    @classmethod
    def clear(cls) -> None:
        _local.clear()
