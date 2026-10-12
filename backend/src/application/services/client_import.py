"""Client CSV import.

A CSV of phone numbers (optionally with a client name) upserts persistent
``Client`` rows by phone. This is a separate upload flow from the
campaign-targeted contact upload (``AudienceService.add_contacts_csv`` /
``CampaignService.add_audience``), which adds contacts to a specific audience
or campaign instead — that flow is untouched and both coexist. This one only
upserts ``Client`` rows by phone — unless the caller also names an audience,
in which case every row that upserts cleanly is filed under it too
(get-or-create by name), so the same CSV also makes the leads
findable/filterable by that audience name later (the lead table's "Audience"
column/filter, VOAD-34).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.audience import (
    AudienceCRUD,
    AudienceMemberCRUD,
    AudienceUploadCRUD,
)
from src.repositories.client import ClientCRUD
from src.schemas.admin import SClientImportResult
from src.utils.phone import normalize_phone

#: Refused before parsing — a runaway upload must not tie up the request
#: handler decoding megabytes of text.
MAX_CSV_BYTES = 5 * 1024 * 1024

#: Downloadable sample of the import format (``GET /clients/import/csv/example``).
EXAMPLE_CSV = "phone,name\n+79991234567,Bob\n+79997654321,\n"

#: Header spellings accepted per column. A first row naming any of them is the
#: header; otherwise the file is headerless and read as ``phone[, name]``.
_COLUMN_ALIASES = {
    "phone": "phone",
    "номер": "phone",
    "телефон": "phone",
    "name": "name",
    "имя": "name",
}


@dataclass
class _ClientImportRow:
    """One CSV row that parsed cleanly, ready to upsert."""

    phone: str
    name: str | None = None


def _read_rows(content: str) -> list[dict[str, str]]:
    """CSV text → one dict (``phone``/``name``) per non-empty data row.

    Columns beyond ``phone`` and ``name`` are ignored; a leading BOM and stray
    whitespace are ignored.
    """
    table = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(content.lstrip("\ufeff")))
        if any(cell.strip() for cell in row)
    ]
    if not table:
        return []
    first = [_COLUMN_ALIASES.get(cell.lower()) for cell in table[0]]
    if any(first):
        names, data = first, table[1:]
    else:
        names, data = ["phone", "name"], table
    return [
        {col: cell for col, cell in zip(names, row) if col is not None} for row in data
    ]


def _parse_client_csv(content: str) -> list[_ClientImportRow | SClientImportResult]:
    """One entry per data row: a row ready for :meth:`ClientImportService.import_rows`,
    or an already-final rejected result for a row with no phone.
    """
    parsed: list[_ClientImportRow | SClientImportResult] = []
    for raw in _read_rows(content):
        phone = raw.get("phone", "")
        if not phone:
            parsed.append(SClientImportResult(phone="", error="missing phone"))
            continue
        parsed.append(_ClientImportRow(phone=phone, name=raw.get("name") or None))
    return parsed


class ClientImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_rows(
        self, rows: list[_ClientImportRow], *, audience_id: int | None = None
    ) -> list[SClientImportResult]:
        """Upsert each row's ``Client`` by phone (and name, when given).

        A bad phone (fails :func:`normalize_phone`) is rejected without
        aborting the batch. Duplicate phones within ``rows``: the last one
        wins, same as a normal upsert. When ``audience_id`` is given, every
        row that upserts cleanly also gets (or refreshes) its membership on
        that audience — same idempotent upsert
        :meth:`AudienceService.add_contacts` uses.
        """
        clients = ClientCRUD(self.session)
        members = AudienceMemberCRUD(self.session) if audience_id is not None else None
        results: list[SClientImportResult] = []
        for row in rows:
            try:
                phone = normalize_phone(row.phone)
            except ValueError as exc:
                results.append(SClientImportResult(phone=row.phone, error=str(exc)))
                continue
            client = await clients.upsert_by_phone(phone, row.name)
            if members is not None:
                await members.upsert(audience_id, client.id, {})
            results.append(SClientImportResult(phone=phone))
        return results

    async def import_csv(
        self,
        content: str,
        *,
        uploaded_by: int,
        filename: str = "",
        audience_name: str | None = None,
    ) -> list[SClientImportResult]:
        """Parse and upsert a client CSV.

        Columns: ``phone`` (required) and ``name`` (optional). The header row
        is optional — a file without one is read as ``phone[, name]``, so a
        plain list of numbers uploads as-is. A row with a missing phone is
        collected as a per-row error instead of aborting the rest of the
        batch. Duplicate phones within one file: the last row wins, same as
        a normal upsert.

        ``audience_name``, if given, resolves to an existing ``Audience``
        (case-insensitive match) or creates one, and every row that upserts
        cleanly is added to it — so the resulting ``AudienceUpload`` row
        (this batch's entry in "История загрузок") is tied to that audience
        the same way an audience-targeted upload's is, instead of always
        recording ``audience_id=None``.
        """
        audience_id: int | None = None
        if audience_name and audience_name.strip():
            audiences = AudienceCRUD(self.session)
            audience = await audiences.get_by_name(audience_name)
            if audience is None:
                audience = await audiences.create({"name": audience_name.strip()})
            audience_id = audience.id

        parsed = _parse_client_csv(content)
        rows = [row for row in parsed if isinstance(row, _ClientImportRow)]
        row_results_list = await self.import_rows(rows, audience_id=audience_id)
        row_results = iter(row_results_list)
        results = [
            item if isinstance(item, SClientImportResult) else next(row_results)
            for item in parsed
        ]
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
