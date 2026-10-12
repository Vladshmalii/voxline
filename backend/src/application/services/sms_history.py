"""Reading SMS history: one set of filters behind the list page and its export.

The list and the file are the same question asked twice — "which messages
match what the admin selected" — so the clauses are built here once and both
routes ask this service, never their own copy of the WHERE.
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.export import Column, ExportFile, write_table
from src.common.enums.export import ExportFormatEnum
from src.models.call import Call
from src.models.messaging import Message
from src.repositories.base import icu_contains
from src.repositories.messaging import MessageCRUD
from src.schemas.filters import SSmsFilters
from src.settings import SETTINGS

SMS_COLUMNS = (
    Column("ID", lambda r: r.id),
    Column("Создано", lambda r: r.created_at),
    Column("Отправлено", lambda r: r.sent_at),
    Column("Финальный статус в", lambda r: r.settled_at),
    Column("Статус", lambda r: r.status),
    Column("Получатель", lambda r: r.to_number),
    Column("Отправитель", lambda r: r.sender),
    Column("Текст", lambda r: r.body),
    Column("Сегменты", lambda r: r.segments),
    Column("Маршрут", lambda r: r.route_name),
    Column("ID звонка", lambda r: r.call_id),
    Column("Агент", lambda r: r.agent_name),
    Column("Кампания", lambda r: r.campaign_name),
    Column("Источник", lambda r: "call" if r.call_id is not None else "manual"),
    Column("Ошибка", lambda r: r.error),
    Column("ID провайдера", lambda r: r.provider_ref),
)


class SmsHistoryService:
    def __init__(self, session: AsyncSession):
        self.messages = MessageCRUD(session)

    @staticmethod
    def clauses(filters: SSmsFilters) -> list:
        clauses = []
        if filters.messaging_id is not None:
            clauses.append(Message.messaging_id == filters.messaging_id)
        if filters.status is not None:
            clauses.append(Message.status == filters.status)
        if filters.to is not None:
            clauses.append(Message.to_number == filters.to)
        for column, value in (
            (Message.body, filters.search),
            (Message.to_number, filters.to_search),
            (Message.sender, filters.sender),
        ):
            if value and value.strip():
                clauses.append(icu_contains(column, value))
        if filters.date_from:
            clauses.append(Message.created_at >= filters.date_from)
        if filters.date_to and filters.date_to < date.max:
            clauses.append(Message.created_at < filters.date_to + timedelta(days=1))
        if filters.created_from is not None:
            clauses.append(Message.created_at >= filters.created_from)
        if filters.created_to is not None:
            clauses.append(Message.created_at <= filters.created_to)
        if filters.call_id is not None:
            clauses.append(Message.call_id == filters.call_id)
        if filters.source == "call":
            clauses.append(Message.call_id.is_not(None))
        elif filters.source == "manual":
            clauses.append(Message.call_id.is_(None))
        call_clauses = []
        if filters.agent_id is not None:
            call_clauses.append(Call.agent_id == filters.agent_id)
        if filters.campaign_id is not None:
            call_clauses.append(Call.campaign_id == filters.campaign_id)
        if call_clauses:
            clauses.append(Message.call_id.in_(select(Call.id).where(*call_clauses)))
        return clauses

    async def page(self, filters: SSmsFilters, limit: int, offset: int):
        """``([(message, agent_id, agent_name)…], total)`` for one list page."""
        return await self.messages.with_agent(
            *self.clauses(filters), sort=filters.sort, limit=limit, offset=offset
        )

    async def export(
        self, filters: SSmsFilters, fmt: ExportFormatEnum, tz: ZoneInfo
    ) -> ExportFile:
        """Every message the list would show for ``filters``, as one file.

        Raises:
            ExportTooLarge: More than ``export_max_rows`` messages match.
        """
        return await write_table(
            self.messages.export_rows(*self.clauses(filters), sort=filters.sort),
            SMS_COLUMNS,
            fmt,
            tz,
            name="sms",
            max_rows=SETTINGS.export_max_rows,
        )
