"""Organization roster for background processes (worker, scheduler, hooks)."""

from __future__ import annotations

from sqlalchemy import select

from src.core.control.models import Organization
from src.core.db.session import SessionMaker


async def organizations_list(only_active: bool = True) -> list[dict]:
    """``[{"uuid": str, "name": str}]`` straight from the control database."""
    stmt = select(Organization.uuid, Organization.name).order_by(Organization.id)
    if only_active:
        stmt = stmt.where(Organization.is_active.is_(True))
    async with SessionMaker.get_control_session()() as session:
        rows = (await session.execute(stmt)).all()
    return [{"uuid": str(uuid), "name": name} for uuid, name in rows]
