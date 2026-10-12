"""Audience lifecycle and membership.

An audience is a saved list of contacts, independent of any campaign — the
same row shape a campaign's direct contact upload takes
(``SCampaignContactRow``), minus the campaign-template check, which only
makes sense once a campaign is picked (that happens in
``CampaignService.add_audience``, over the exact same ``upload()`` path).
Re-adding a phone already on the audience updates its facts rather than
duplicating the membership.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audience import Audience, AudienceUpload
from src.repositories.audience import (
    AudienceCRUD,
    AudienceMemberCRUD,
    AudienceUploadCRUD,
)
from src.repositories.client import ClientCRUD
from src.schemas import admin
from src.utils.phone import normalize_phone

#: Refused before parsing — a runaway upload must not tie up the request
#: handler decoding megabytes of text.
MAX_CSV_BYTES = 5 * 1024 * 1024

#: Columns mapped onto SCampaignContactRow fields; anything else in the
#: header becomes a custom attribute.
CSV_KNOWN_COLUMNS = frozenset(
    {
        "phone",
        "name",
        "language",
        "player_id",
        "vip_status",
        "last_deposit",
        "last_active",
        "country",
        "timezone",
    }
)


class AudienceError(ValueError):
    """The operation cannot proceed; the message says why."""


def _parse_contact_csv(
    content: str,
) -> list[admin.SCampaignContactRow | admin.SAudienceUploadResult]:
    """One entry per data row: a row ready for :meth:`AudienceService.add_contacts`,
    or an already-final rejected result for a row that never parses that far.
    """
    parsed: list[admin.SCampaignContactRow | admin.SAudienceUploadResult] = []
    for raw in csv.DictReader(io.StringIO(content)):
        phone = (raw.get("phone") or "").strip()
        if not phone:
            parsed.append(admin.SAudienceUploadResult(phone="", error="missing phone"))
            continue

        last_deposit: float | None = None
        if raw.get("last_deposit"):
            try:
                last_deposit = float(raw["last_deposit"])
            except ValueError:
                parsed.append(
                    admin.SAudienceUploadResult(
                        phone=phone,
                        error=f"invalid last_deposit: {raw['last_deposit']!r}",
                    )
                )
                continue

        last_active: datetime | None = None
        if raw.get("last_active"):
            try:
                last_active = datetime.fromisoformat(raw["last_active"])
            except ValueError:
                parsed.append(
                    admin.SAudienceUploadResult(
                        phone=phone,
                        error=f"invalid last_active: {raw['last_active']!r}",
                    )
                )
                continue

        attributes = {
            key: value
            for key, value in raw.items()
            if key not in CSV_KNOWN_COLUMNS and value not in (None, "")
        }
        parsed.append(
            admin.SCampaignContactRow(
                phone=phone,
                name=raw.get("name") or None,
                language=raw.get("language") or None,
                player_id=raw.get("player_id") or None,
                vip_status=raw.get("vip_status") or None,
                last_deposit=last_deposit,
                last_active=last_active,
                country=raw.get("country") or None,
                timezone=raw.get("timezone") or None,
                attributes=attributes,
            )
        )
    return parsed


class AudienceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get(self, audience_id: int) -> Audience:
        audience = await AudienceCRUD(self.session).get_one_or_none(
            Audience.id == audience_id
        )
        if audience is None:
            raise AudienceError(f"audience {audience_id} not found")
        return audience

    async def _member_count(self, audience_id: int) -> int:
        counts = await AudienceMemberCRUD(self.session).count_by_audience([audience_id])
        return counts.get(audience_id, 0)

    async def list(
        self, *, include_archived: bool = False, limit: int = 100, offset: int = 0
    ) -> tuple[list[tuple[Audience, int]], int]:
        """``([(audience, member_count)…], total)``, newest first.

        Archived audiences are hidden unless ``include_archived``.
        """
        clauses = [] if include_archived else [Audience.is_archived.is_(False)]
        audiences, count = await AudienceCRUD(self.session).get_many_with_count(
            *clauses, order_by=Audience.id.desc(), limit=limit, offset=offset
        )
        counts = await AudienceMemberCRUD(self.session).count_by_audience(
            [a.id for a in audiences]
        )
        return [(a, counts.get(a.id, 0)) for a in audiences], count

    async def get(self, audience_id: int) -> tuple[Audience, int]:
        """``(audience, member_count)``.

        Raises:
            AudienceError: If the audience does not exist.
        """
        audience = await self._get(audience_id)
        return audience, await self._member_count(audience_id)

    async def create(self, data: admin.SAudienceCreate) -> Audience:
        return await AudienceCRUD(self.session).create(data.model_dump())

    async def update(
        self, audience_id: int, data: admin.SAudienceUpdate
    ) -> tuple[Audience, int]:
        """Apply the fields ``data`` sets; ``(audience, member_count)``.

        Raises:
            AudienceError: If the audience does not exist.
        """
        audience = await self._get(audience_id)
        values = data.model_dump(exclude_unset=True)
        if values:
            await AudienceCRUD(self.session).update(
                Audience.id == audience_id, data=values
            )
            self.session.expire(audience)
        audience = await self._get(audience_id)
        return audience, await self._member_count(audience_id)

    async def delete(self, audience_id: int) -> None:
        """Delete an audience and its members (``AudienceMember`` cascades).

        Safe regardless of campaigns it has fed: adding an audience to a
        campaign copies its members into that campaign's own ``Call`` rows,
        so nothing else references the audience itself.
        """
        await self._get(audience_id)
        await AudienceCRUD(self.session).delete(Audience.id == audience_id)

    async def uploads(
        self,
        *,
        audience_id: int | None = None,
        uploaded_by: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[tuple[AudienceUpload, str | None]], int]:
        """Upload-batch history (VOAD-34), newest first.

        Returns:
            ``([(upload, audience_name)…], total)`` — the name is None for an
            upload tied to no audience (the VOAD-32 segment import without one).
        """
        clauses = []
        if audience_id is not None:
            clauses.append(AudienceUpload.audience_id == audience_id)
        if uploaded_by is not None:
            clauses.append(AudienceUpload.uploaded_by == uploaded_by)
        uploads, count = await AudienceUploadCRUD(self.session).get_many_with_count(
            *clauses, order_by=AudienceUpload.id.desc(), limit=limit, offset=offset
        )
        names = await AudienceCRUD(self.session).names_by_id(
            [u.audience_id for u in uploads if u.audience_id is not None]
        )
        rows = [
            (u, names.get(u.audience_id) if u.audience_id else None) for u in uploads
        ]
        return rows, count

    async def add_contacts(
        self,
        audience_id: int,
        rows: list[admin.SCampaignContactRow],
        *,
        uploaded_by: int,
        filename: str = "",
    ) -> list[admin.SAudienceUploadResult]:
        """Upsert clients and add (or refresh) them as members of this audience.

        Unlike a campaign upload there is no template to render and no
        callable-client check — an audience is just a list; both happen when
        it is later added to a campaign. Records one ``AudienceUpload`` row
        for this batch (VOAD-34's "История загрузок"), regardless of whether
        it came from JSON rows or a CSV file.
        """
        await self._get(audience_id)
        clients = ClientCRUD(self.session)
        members = AudienceMemberCRUD(self.session)
        results: list[admin.SAudienceUploadResult] = []
        for row in rows:
            try:
                phone = normalize_phone(row.phone)
            except ValueError as exc:
                results.append(
                    admin.SAudienceUploadResult(phone=row.phone, error=str(exc))
                )
                continue
            client = await clients.upsert_by_phone(phone, row.name)
            member = await members.upsert(
                audience_id,
                client.id,
                {
                    "language": row.language,
                    "bonuses": row.bonuses,
                    "player_id": row.player_id,
                    "vip_status": row.vip_status,
                    "last_deposit": row.last_deposit,
                    "last_active": row.last_active,
                    "country": row.country,
                    "timezone": row.timezone,
                    "attributes": row.attributes,
                },
            )
            results.append(
                admin.SAudienceUploadResult(phone=phone, member_id=member.id)
            )
        invalid = sum(1 for r in results if r.error is not None)
        await AudienceUploadCRUD(self.session).create(
            {
                "audience_id": audience_id,
                "uploaded_by": uploaded_by,
                "filename": filename,
                "total_rows": len(results),
                "valid_rows": len(results) - invalid,
                "invalid_rows": invalid,
            }
        )
        return results

    async def add_contacts_csv(
        self, audience_id: int, content: str, *, uploaded_by: int, filename: str = ""
    ) -> list[admin.SAudienceUploadResult]:
        """Same as :meth:`add_contacts`, from a CSV file instead of JSON rows."""
        parsed = _parse_contact_csv(content)
        rows = [row for row in parsed if isinstance(row, admin.SCampaignContactRow)]
        row_results = iter(
            await self.add_contacts(
                audience_id, rows, uploaded_by=uploaded_by, filename=filename
            )
        )
        return [
            item if isinstance(item, admin.SAudienceUploadResult) else next(row_results)
            for item in parsed
        ]
