from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.models.audience import Audience, AudienceMember, AudienceUpload
from src.repositories.base import CRUD


class AudienceCRUD(CRUD[Audience]):
    model = Audience

    async def get_by_name(self, name: str) -> Audience | None:
        """Case-insensitive exact match — the get-or-create-by-name step the
        CSV import flows use so an operator can type a name they've already
        used without creating a near-duplicate audience."""
        return await self.get_one_or_none(
            func.lower(Audience.name) == name.strip().lower()
        )

    async def names_by_id(self, audience_ids: list[int]) -> dict[int, str]:
        """Audience name per id, for the audiences a list page points at."""
        if not audience_ids:
            return {}
        rows = await self.session.execute(
            select(Audience.id, Audience.name).where(Audience.id.in_(audience_ids))
        )
        return dict(rows.all())


class AudienceUploadCRUD(CRUD[AudienceUpload]):
    """Upload-history table (VOAD-34's "История загрузок").

    A row is written by both ``AudienceService.add_contacts``/
    ``add_contacts_csv`` (audience-targeted upload) and
    ``ClientImportService.import_csv`` (the VOAD-32 segment import, tied to
    an audience only when the caller names one — see its own docstring).
    """

    model = AudienceUpload


class AudienceMemberCRUD(CRUD[AudienceMember]):
    model = AudienceMember

    async def count_by_audience(self, audience_ids: list[int]) -> dict[int, int]:
        """Member count per audience, for the audiences a list page is showing."""
        if not audience_ids:
            return {}
        rows = await self.session.execute(
            select(AudienceMember.audience_id, func.count())
            .where(AudienceMember.audience_id.in_(audience_ids))
            .group_by(AudienceMember.audience_id)
        )
        return dict(rows.all())

    async def audience_names_by_client(
        self, client_ids: list[int]
    ) -> dict[int, list[str]]:
        """Which Audience(s) each of these clients belongs to, name only — one
        bulk query for a whole page rather than a join per lead row, since
        membership is many-to-many via AudienceMember and not a Client column."""
        result: dict[int, list[str]] = {cid: [] for cid in client_ids}
        if not client_ids:
            return result
        rows = await self.session.execute(
            select(AudienceMember.client_id, Audience.name)
            .join(Audience, Audience.id == AudienceMember.audience_id)
            .where(AudienceMember.client_id.in_(client_ids))
            .order_by(Audience.name)
        )
        for client_id, name in rows.all():
            result[client_id].append(name)
        return result

    async def upsert(
        self, audience_id: int, client_id: int, data: dict[str, Any]
    ) -> AudienceMember:
        """Add a client to an audience, or refresh its facts if already on it."""
        stmt = (
            pg_insert(AudienceMember)
            .values(audience_id=audience_id, client_id=client_id, **data)
            .on_conflict_do_update(
                index_elements=[AudienceMember.audience_id, AudienceMember.client_id],
                # No facts to refresh (phone-only import): a no-op update, so
                # the conflict path still returns the existing row.
                set_=data or {"audience_id": audience_id},
            )
            .returning(AudienceMember)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
