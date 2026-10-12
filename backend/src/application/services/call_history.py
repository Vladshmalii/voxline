"""Reading call history: one set of filters behind the list page and its export.

Same split as ``sms_history``: the list and the file answer the same question,
so the clauses and the ordering are built here once and both routes ask this
service. The other reads over calls — the status/outcome summary, an attempt's
recording — live here too. Mutations (originate, cancel, tags) stay in
``CallService``.
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import column, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.export import Column, ExportFile, write_table
from src.common.enums.export import ExportFormatEnum
from src.models.call import Call, CallAttempt
from src.models.client import Client
from src.repositories.base import icu_contains
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.schemas.filters import SCallFilters
from src.settings import SETTINGS


def _duration(row) -> int | None:
    # Same rule as Call.duration_seconds, over the latest attempt's columns.
    if row.answered_at is None or row.ended_at is None:
        return None
    return max(0, int((row.ended_at - row.answered_at).total_seconds()))


_CALL_COLUMNS = (
    Column("ID", lambda r: r.id),
    Column("UUID", lambda r: r.uuid),
    Column("Создан", lambda r: r.created_at),
    Column("Направление", lambda r: r.direction),
    Column("Статус", lambda r: r.status),
    Column("Результат", lambda r: r.outcome),
    Column("Тональность", lambda r: r.sentiment),
    Column("Причина отказа", lambda r: r.reason_category),
    Column("Выбранное предложение", lambda r: r.selected_offer),
    Column("Теги", lambda r: r.tags),
    Column("Агент", lambda r: r.agent_name),
    Column("Кампания", lambda r: r.campaign_name),
    Column("Клиент", lambda r: r.client_name),
    Column("Телефон клиента", lambda r: r.client_phone),
    Column("Номер звонящего", lambda r: r.from_number),
    Column("Язык", lambda r: r.language),
    Column("Страна", lambda r: r.country),
    Column("ID игрока", lambda r: r.player_id),
    Column("VIP", lambda r: r.vip_status),
    Column("Попыток", lambda r: r.attempts_made),
    Column("Обратный звонок", lambda r: r.is_callback),
    Column("Начало разговора", lambda r: r.answered_at),
    Column("Конец разговора", lambda r: r.ended_at),
    Column("Длительность, сек", _duration),
    Column("Итог разговора", lambda r: r.summary),
)


def call_columns(full_access: bool) -> tuple[Column, ...]:
    """The export's columns; ``uuid`` is internal, as on the list (VOAD-28/31)."""
    if full_access:
        return _CALL_COLUMNS
    return tuple(c for c in _CALL_COLUMNS if c.header != "UUID")


def _conversation_contains(value: str):
    # Search speech content, not JSON keys, role labels or system/event data.
    messages = (
        func.jsonb_array_elements(CallAttempt.messages)
        .table_valued(column("value", JSONB))
        .alias("transcript_message")
    )
    speech = (
        select(1)
        .select_from(messages)
        .where(
            messages.c.value["role"].astext.in_(["user", "assistant"]),
            func.jsonb_typeof(messages.c.value["content"]) == "string",
            icu_contains(messages.c.value["content"].astext, value),
        )
        .exists()
    )
    return (
        select(1)
        .select_from(CallAttempt)
        .where(
            CallAttempt.call_id == Call.id,
            or_(icu_contains(CallAttempt.summary, value), speech),
        )
        .correlate(Call)
        .exists()
    )


class RecordingNotFound(LookupError):
    """No recording to point to; the message says which part is missing."""


class CallHistoryService:
    def __init__(self, session: AsyncSession):
        self.calls = CallCRUD(session)
        self.attempts = CallAttemptCRUD(session)

    @staticmethod
    def clauses(filters: SCallFilters) -> list:
        clauses = []
        if filters.call_id is not None:
            clauses.append(Call.id == filters.call_id)
        if filters.agent_id is not None:
            clauses.append(Call.agent_id == filters.agent_id)
        if filters.campaign_id is not None:
            clauses.append(Call.campaign_id == filters.campaign_id)
        if filters.client_id is not None:
            clauses.append(Call.client_id == filters.client_id)
        if filters.status is not None:
            clauses.append(Call.status == filters.status)
        if filters.attempt_status is not None:
            # Status of the call's latest attempt (the leg the UI's "Attempts"
            # view shows last) — Call.status is the lifecycle, not the leg's.
            clauses.append(
                select(CallAttempt.status)
                .where(CallAttempt.call_id == Call.id)
                .order_by(CallAttempt.seq.desc())
                .limit(1)
                .correlate(Call)
                .scalar_subquery()
                == filters.attempt_status
            )
        if filters.outcome is not None:
            clauses.append(Call.outcome == filters.outcome)
        if filters.sentiment is not None:
            clauses.append(Call.sentiment == filters.sentiment)
        if filters.reason_category is not None:
            clauses.append(Call.reason_category == filters.reason_category)
        if filters.direction is not None:
            clauses.append(Call.direction == filters.direction)
        if filters.search and filters.search.strip():
            clauses.append(_conversation_contains(filters.search))
        if filters.client_search and filters.client_search.strip():
            clauses.append(
                Call.client_id.in_(
                    select(Client.id).where(
                        or_(
                            icu_contains(Client.name, filters.client_search),
                            icu_contains(Client.phone, filters.client_search),
                        )
                    )
                )
            )
        if filters.from_search and filters.from_search.strip():
            clauses.append(icu_contains(Call.from_number, filters.from_search))
        if filters.language and filters.language.strip():
            clauses.append(
                func.lower(Call.language) == filters.language.strip().lower()
            )
        if filters.has_recording is not None:
            recorded = (
                select(1)
                .select_from(CallAttempt)
                .where(
                    CallAttempt.call_id == Call.id,
                    CallAttempt.recording_url.is_not(None),
                    CallAttempt.recording_url != "",
                )
                .correlate(Call)
                .exists()
            )
            clauses.append(recorded if filters.has_recording else ~recorded)
        if filters.date_from:
            clauses.append(Call.created_at >= filters.date_from)
        if filters.date_to and filters.date_to < date.max:
            clauses.append(Call.created_at < filters.date_to + timedelta(days=1))
        if filters.created_from is not None:
            clauses.append(Call.created_at >= filters.created_from)
        if filters.created_to is not None:
            clauses.append(Call.created_at <= filters.created_to)
        return clauses

    @staticmethod
    def order_by(sort: str | None) -> tuple:
        # Call.duration_seconds is a Python property (derived from the latest
        # attempt, not a column), so it needs its own SQL expression to be
        # sortable — the same "latest attempt by seq" the property reads.
        latest_attempt_duration = (
            select(
                func.extract("epoch", CallAttempt.ended_at - CallAttempt.answered_at)
            )
            .where(CallAttempt.call_id == Call.id)
            .order_by(CallAttempt.seq.desc())
            .limit(1)
            .correlate(Call)
            .scalar_subquery()
        )
        order_map = {
            "status": lambda: Call.status.asc(),
            "-status": lambda: Call.status.desc(),
            "created_at": lambda: Call.created_at.asc(),
            "-created_at": lambda: Call.created_at.desc(),
            "duration": lambda: latest_attempt_duration.asc(),
            "-duration": lambda: latest_attempt_duration.desc(),
            "duration_seconds": lambda: latest_attempt_duration.asc(),
            "-duration_seconds": lambda: latest_attempt_duration.desc(),
            "id": lambda: Call.id.asc(),
            "-id": lambda: Call.id.desc(),
        }
        order = order_map.get(sort or "", lambda: Call.id.desc())()

        # Preserve legacy sort names/default while preventing equal values from
        # moving between pages. Missing durations belong at the end in both orders.
        if sort in ("duration", "-duration", "duration_seconds", "-duration_seconds"):
            order = order.nulls_last()
        tie_order = (
            Call.id.desc() if not sort or sort.startswith("-") else Call.id.asc()
        )
        return order, tie_order

    async def page(self, filters: SCallFilters, limit: int, offset: int):
        """``([(call, sms_sent)…], total)`` for one list page (VOAD-78)."""
        calls, count = await self.calls.filtered_page(
            *self.clauses(filters),
            order_by=self.order_by(filters.sort),
            limit=limit,
            offset=offset,
        )
        sms_by_call = await self.calls.sms_sent_counts([c.id for c in calls])
        return [(c, sms_by_call.get(c.id, 0)) for c in calls], count

    async def export(
        self,
        filters: SCallFilters,
        fmt: ExportFormatEnum,
        tz: ZoneInfo,
        full_access: bool,
    ) -> ExportFile:
        """Every call the list would show for ``filters``, as one file.

        Raises:
            ExportTooLarge: More than ``export_max_rows`` calls match.
        """
        return await write_table(
            self.calls.export_rows(
                *self.clauses(filters), order_by=self.order_by(filters.sort)
            ),
            call_columns(full_access),
            fmt,
            tz,
            name="calls",
            max_rows=SETTINGS.export_max_rows,
        )

    async def summary(self) -> dict:
        """Aggregate counts by status and outcome across calls."""
        status_counts = await self.calls.global_status_counts()
        outcome_counts = await self.calls.global_outcome_counts()
        total = await self.calls.total_count()
        return {
            "total": total,
            "statuses": {status.value: count for status, count in status_counts},
            "outcomes": {outcome.value: count for outcome, count in outcome_counts},
        }

    async def recording(self, call_id: int, attempt_id: int) -> CallAttempt:
        """The attempt, when it has a stored ``recording_url`` (VOAD-37).

        Raises:
            RecordingNotFound: The call or attempt is missing, the attempt was
                never answered, or nothing is stored for it yet.
        """
        attempt = await self.attempts.get_one_or_none(
            CallAttempt.id == attempt_id, CallAttempt.call_id == call_id
        )
        if attempt is None:
            if not await self.calls.exists(Call.id == call_id):
                raise RecordingNotFound("call not found")
            raise RecordingNotFound("call attempt not found")
        if attempt.recording_url is None:
            if attempt.answered_at is None:
                raise RecordingNotFound(
                    "call attempt was never answered; no recording exists"
                )
            raise RecordingNotFound("no recording is stored for this call attempt")
        return attempt
