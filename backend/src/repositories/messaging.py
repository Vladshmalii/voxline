from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from src.common.enums.engine import MESSAGE_STATUS_RANK, MessageStatusEnum
from src.models.agent import VoiceAgent
from src.models.call import Call
from src.models.campaign import Campaign
from src.models.messaging import Message, Messaging
from src.repositories.base import CRUD
from src.schemas.messaging import MessagingConfig


class MessagingCRUD(CRUD[Messaging]):
    model = Messaging

    @staticmethod
    def build_config(row: Messaging) -> MessagingConfig:
        """The row as the messaging adapters consume it.

        Args:
            row: A messaging row.

        Returns:
            The plain pydantic binding, validated (an unknown adapter string
            fails here, naming the row, not mid-send).
        """
        return MessagingConfig(
            adapter=row.adapter,
            account_id=row.account_id,
            auth_token=row.auth_token,
            sender=row.sender,
            sender_pool_id=row.sender_pool_id,
            control_url=row.control_url,
            capabilities=row.capabilities,
            options=row.options,
        )


class MessageCRUD(CRUD[Message]):
    model = Message

    @staticmethod
    def _order(sort: str):
        return (
            (Message.created_at.asc(), Message.id.asc())
            if sort == "oldest"
            else (Message.created_at.desc(), Message.id.desc())
        )

    async def with_agent(self, *clauses, limit=100, offset=0, sort="newest"):
        """Page messages with their call's agent, keeping unlinked history.

        Select scalar call/agent columns so listing SMS does not load call
        attempts, agent models or configuration. Both joins are many-to-one.
        """
        rows = await self.session.execute(
            select(Message, Call.agent_id, VoiceAgent.name)
            .outerjoin(Call, Message.call_id == Call.id)
            .outerjoin(VoiceAgent, Call.agent_id == VoiceAgent.id)
            .where(*clauses)
            .order_by(*self._order(sort))
            .limit(limit)
            .offset(offset)
        )
        count = await self.session.scalar(
            select(func.count(Message.id)).where(*clauses)
        )
        return rows.all(), count

    async def with_route(self, message_uuid: str) -> tuple[Message, Messaging] | None:
        """The message and the row that sent it, or None if either is gone."""
        row = (
            await self.session.execute(
                select(Message, Messaging)
                .join(Messaging, Message.messaging_id == Messaging.id)
                .where(Message.uuid == message_uuid)
            )
        ).one_or_none()
        return (row[0], row[1]) if row else None

    async def export_rows(self, *clauses, sort="newest", batch=1000):
        """Every matching message as flat rows, in list order, ``batch`` at a time.

        A server-side cursor, so an export of the whole history never sits in
        memory at once. Columns, not entities: nothing lazy can fire.
        """
        result = await self.session.stream(
            select(
                Message.id,
                Message.created_at,
                Message.sent_at,
                Message.settled_at,
                Message.status,
                Message.to_number,
                Message.sender,
                Message.body,
                Message.segments,
                Messaging.name.label("route_name"),
                Message.call_id,
                VoiceAgent.name.label("agent_name"),
                Campaign.name.label("campaign_name"),
                Message.error,
                Message.provider_ref,
            )
            .outerjoin(Messaging, Message.messaging_id == Messaging.id)
            .outerjoin(Call, Message.call_id == Call.id)
            .outerjoin(VoiceAgent, Call.agent_id == VoiceAgent.id)
            .outerjoin(Campaign, Call.campaign_id == Campaign.id)
            .where(*clauses)
            .order_by(*self._order(sort))
            .execution_options(yield_per=batch)
        )
        try:
            async for rows in result.partitions():
                yield rows
        finally:
            await result.close()

    async def stats_counts(self, midnight: datetime, *clauses):
        """One aggregate per status, including today's rows and segments."""
        rows = await self.session.execute(
            select(
                Message.status,
                func.count(Message.id).label("count"),
                func.count(Message.id)
                .filter(Message.created_at >= midnight)
                .label("today"),
                func.sum(Message.segments).label("segments"),
            )
            .where(*clauses)
            .group_by(Message.status)
        )
        return rows.all()

    async def daily_counts(self, since: date, until: date, *clauses):
        day = func.date_trunc("day", Message.created_at).label("day")
        rows = await self.session.execute(
            select(
                day,
                func.count(Message.id).label("total"),
                func.count(Message.id)
                .filter(Message.status == MessageStatusEnum.delivered)
                .label("delivered"),
                func.count(Message.id)
                .filter(
                    Message.status.in_(
                        [MessageStatusEnum.failed, MessageStatusEnum.undelivered]
                    )
                )
                .label("failed"),
            )
            .where(
                Message.created_at >= since,
                Message.created_at < until + timedelta(days=1),
                *clauses,
            )
            .group_by(day)
            .order_by(day)
        )
        return rows.all()

    async def advance(
        self,
        *clauses,
        status: MessageStatusEnum,
        data: dict | None = None,
    ) -> int:
        """Move a message forward to `status`, never backward.

        Carriers report out of order: a ``sent`` callback arriving after
        ``delivered`` is ordinary, and the naive write would erase the verdict
        that matters. The guard is in the WHERE clause rather than a
        read-then-write, so two hooks replicas racing on the same message
        resolve without coordination — the later, lower-ranked one updates
        zero rows.

        Args:
            *clauses: Which message (usually ``Message.uuid == …``).
            status: The status to move to.
            data: Other columns to set alongside it.

        Returns:
            Rows updated: 1 when the status advanced, 0 when it did not.
        """
        behind = [
            value
            for value, rank in MESSAGE_STATUS_RANK.items()
            if rank < MESSAGE_STATUS_RANK[status]
        ]
        if not behind:
            return 0  # nothing ranks below queued; a queued callback is noise
        return await self.update(
            *clauses,
            Message.status.in_(behind),
            data={"status": status, **(data or {})},
        )
