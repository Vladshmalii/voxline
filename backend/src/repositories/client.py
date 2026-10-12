from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.common.enums.campaign import ClientSegmentEnum, ClientStatusEnum
from src.models.client import Client
from src.repositories.base import CRUD

#: Fields besides ``name`` that upsert-by-phone will refresh when a caller
#: provides them. Kept as a tuple, not individual kwargs per field, so a
#: future field is one entry here, not a signature change at every call site.
_UPSERT_FACT_FIELDS = (
    "country",
    "language",
    "vip_status",
    "last_deposit",
    "last_active",
    "segment",
)


class ClientCRUD(CRUD[Client]):
    model = Client

    async def total_count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Client))
        return result.scalar_one()

    async def countries(self) -> list[str]:
        """Unique non-empty countries among existing clients."""
        rows = await self.session.execute(
            select(Client.country)
            .where(Client.country.is_not(None), Client.country != "")
            .distinct()
            .order_by(Client.country)
        )
        return [r[0] for r in rows.all() if r[0]]

    async def global_segment_counts(self) -> list[tuple[ClientSegmentEnum, int]]:
        """Every lead grouped by cold/warm/hot (VOAD-38 dashboard)."""
        rows = await self.session.execute(
            select(Client.segment, func.count())
            .where(Client.segment.is_not(None))
            .group_by(Client.segment)
        )
        return list(rows.all())

    async def global_status_counts(self) -> list[tuple[ClientStatusEnum, int]]:
        """Every lead grouped by active/do_not_call/blocked (VOAD-38 dashboard)."""
        rows = await self.session.execute(
            select(Client.status, func.count()).group_by(Client.status)
        )
        return list(rows.all())

    async def upsert_by_phone(
        self,
        phone: str,
        name: str | None = None,
        *,
        country: str | None = None,
        language: str | None = None,
        vip_status: str | None = None,
        last_deposit: float | None = None,
        last_active: datetime | None = None,
        segment: ClientSegmentEnum | None = None,
    ) -> Client:
        """Get-or-create a client by normalized phone; a provided value updates
        the row, an omitted one leaves what is there. Never touches ``status``
        (do-not-call/blocked) — that gate is set only by the code paths that
        own it.

        Args:
            phone: Normalized phone (``utils.phone.normalize_phone``).
            name: Client name from the upload/originate request, optional.
            country: Persistent, cross-campaign fact (VOAD-32/33), optional.
            language: Persistent, cross-campaign fact, optional.
            vip_status: Persistent, cross-campaign fact, optional.
            last_deposit: Persistent, cross-campaign fact, optional.
            last_active: Persistent, cross-campaign fact, optional.
            segment: Lead-temperature label (VOAD-32), optional.

        Returns:
            The persisted client row.
        """
        facts: dict[str, Any] = {
            "country": country,
            "language": language,
            "vip_status": vip_status,
            "last_deposit": last_deposit,
            "last_active": last_active,
            "segment": segment,
        }
        provided = {
            field: facts[field]
            for field in _UPSERT_FACT_FIELDS
            if facts[field] is not None
        }

        insert_values: dict[str, Any] = {"phone": phone, "name": name or "", **provided}
        update_values: dict[str, Any] = dict(provided)
        if name:
            update_values["name"] = name
        if not update_values:
            update_values = {"phone": phone}

        stmt = (
            pg_insert(Client)
            .values(**insert_values)
            .on_conflict_do_update(
                index_elements=[Client.phone],
                set_=update_values,
            )
            .returning(Client)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
