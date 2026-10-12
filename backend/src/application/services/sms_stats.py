from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums.engine import MessageStatusEnum
from src.models.messaging import Message
from src.repositories.messaging import MessageCRUD
from src.schemas.sms_stats import (
    SMessageStatusCount,
    SSmsDailyCount,
    SSmsStatsOverview,
    SSmsStatsTimeseries,
)


class SmsStatsService:
    def __init__(self, session: AsyncSession):
        self.messages = MessageCRUD(session)

    @staticmethod
    def filters(messaging_id: int | None, to: str | None):
        clauses = []
        if messaging_id is not None:
            clauses.append(Message.messaging_id == messaging_id)
        if to is not None:
            clauses.append(Message.to_number == to)
        return clauses

    async def overview(self, messaging_id: int | None = None, to: str | None = None):
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self.messages.stats_counts(
            midnight, *self.filters(messaging_id, to)
        )
        counts = {status: 0 for status in MessageStatusEnum}
        today = segments = 0
        for row in rows:
            counts[row.status] = row.count
            today += row.today
            segments += row.segments or 0
        delivered = counts[MessageStatusEnum.delivered]
        undelivered = counts[MessageStatusEnum.undelivered]
        settled = delivered + undelivered
        total = sum(counts.values())
        return SSmsStatsOverview(
            total=total,
            today=today,
            sent=counts[MessageStatusEnum.sent] + settled,
            delivered=delivered,
            errors=counts[MessageStatusEnum.failed] + undelivered,
            pending=counts[MessageStatusEnum.queued] + counts[MessageStatusEnum.sent],
            segments=segments,
            delivery_rate=delivered / total if total else None,
            by_status=[
                SMessageStatusCount(status=status, count=count)
                for status, count in counts.items()
            ],
        )

    async def timeseries(
        self,
        date_from: date,
        date_to: date,
        messaging_id: int | None = None,
        to: str | None = None,
    ):
        rows = await self.messages.daily_counts(
            date_from, date_to, *self.filters(messaging_id, to)
        )
        by_day = {row.day.date(): row for row in rows}
        days = []
        for offset in range((date_to - date_from).days + 1):
            day = date_from + timedelta(days=offset)
            row = by_day.get(day)
            days.append(
                SSmsDailyCount(
                    date=day,
                    total=row.total if row else 0,
                    delivered=row.delivered if row else 0,
                    failed=row.failed if row else 0,
                )
            )
        return SSmsStatsTimeseries(days=days)
