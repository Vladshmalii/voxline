from datetime import date, datetime, timedelta

from sqlalchemy import exists, func, or_, select, true, update

from src.common.enums.campaign import (
    CallLifecycleEnum,
    CallOutcomeEnum,
    CampaignStatusEnum,
    ReasonCategoryEnum,
    SentimentEnum,
)
from src.common.enums.engine import CallDirectionEnum, CallStatusEnum, MessageStatusEnum
from src.models.agent import VoiceAgent
from src.models.call import Call, CallAttempt
from src.models.campaign import Campaign
from src.models.client import Client
from src.models.messaging import Message
from src.repositories.base import CRUD


class CallCRUD(CRUD[Call]):
    model = Call

    async def filtered_page(self, *clauses, order_by, limit, offset):
        """Apply the same filters to the page and count, with stable tie ordering."""
        result = await self.session.execute(
            select(Call).where(*clauses).order_by(*order_by).limit(limit).offset(offset)
        )
        count = await self.session.scalar(
            select(func.count()).select_from(Call).where(*clauses)
        )
        return result.unique().scalars().all(), count

    async def export_rows(self, *clauses, order_by, batch=1000):
        """Every matching call as flat rows, in list order, ``batch`` at a time.

        Columns, not ``Call`` entities: loading the entity would pull every
        attempt's transcript (``attempts`` is selectin) for a file that only
        shows the latest attempt's timing and summary — read here through a
        LATERAL join, the same "latest by seq" ``Call.duration_seconds`` uses.
        A server-side cursor keeps the whole history out of memory.
        """
        latest = (
            select(CallAttempt.answered_at, CallAttempt.ended_at, CallAttempt.summary)
            .where(CallAttempt.call_id == Call.id)
            .order_by(CallAttempt.seq.desc())
            .limit(1)
            .correlate(Call)
            .lateral("latest_attempt")
        )
        result = await self.session.stream(
            select(
                Call.id,
                Call.uuid,
                Call.created_at,
                Call.direction,
                Call.status,
                Call.outcome,
                Call.sentiment,
                Call.reason_category,
                Call.selected_offer,
                Call.tags,
                VoiceAgent.name.label("agent_name"),
                Campaign.name.label("campaign_name"),
                Client.name.label("client_name"),
                Client.phone.label("client_phone"),
                Call.from_number,
                Call.language,
                Call.country,
                Call.player_id,
                Call.vip_status,
                Call.attempts_made,
                Call.is_callback,
                latest.c.answered_at,
                latest.c.ended_at,
                latest.c.summary,
            )
            .select_from(Call)
            .outerjoin(Client, Call.client_id == Client.id)
            .outerjoin(Campaign, Call.campaign_id == Campaign.id)
            .outerjoin(VoiceAgent, Call.agent_id == VoiceAgent.id)
            .outerjoin(latest, true())
            .where(*clauses)
            .order_by(*order_by)
            .execution_options(yield_per=batch)
        )
        try:
            async for rows in result.partitions():
                yield rows
        finally:
            await result.close()

    async def reason_category_counts(
        self, campaign_id: int
    ) -> list[tuple[ReasonCategoryEnum, int]]:
        """Calls of this campaign grouped by their declined-reason category."""
        rows = await self.session.execute(
            select(Call.reason_category, func.count())
            .where(Call.campaign_id == campaign_id, Call.reason_category.is_not(None))
            .group_by(Call.reason_category)
        )
        return list(rows.all())

    async def answered_counts_by_client(self, client_ids: list[int]) -> dict[int, int]:
        """How many answered calls (conversation attempts) were made to each client."""
        result: dict[int, int] = {cid: 0 for cid in client_ids}
        if not client_ids:
            return result
        rows = await self.session.execute(
            select(Call.client_id, func.count())
            .join(CallAttempt, CallAttempt.call_id == Call.id)
            .where(
                Call.client_id.in_(client_ids),
                CallAttempt.answered_at.is_not(None),
            )
            .group_by(Call.client_id)
        )
        for client_id, count in rows.all():
            result[client_id] = count
        return result

    async def sms_sent_counts(self, call_ids: list[int]) -> dict[int, int]:
        """SMS sent per call, one grouped query for the whole page (VOAD-78)."""
        if not call_ids:
            return {}
        rows = await self.session.execute(
            select(Message.call_id, func.count())
            .where(
                Message.call_id.in_(call_ids),
                Message.status.in_(SMS_SENT_STATUSES),
            )
            .group_by(Message.call_id)
        )
        return {call_id: count for call_id, count in rows.all()}

    async def status_counts(
        self, campaign_id: int
    ) -> list[tuple[CallLifecycleEnum, int]]:
        """This campaign's calls grouped by lifecycle status."""
        rows = await self.session.execute(
            select(Call.status, func.count())
            .where(Call.campaign_id == campaign_id)
            .group_by(Call.status)
        )
        return list(rows.all())

    # -- global (dashboard, VOAD-38) ----------------------------------------
    # One GROUP BY per dimension — a handful of full-table scans (no index on
    # outcome/sentiment/reason_category/direction today, only on status+
    # next_attempt_at for the dispatcher's own claim query) — rather than one
    # COUNT(*) per enum *value* the frontend would otherwise have to issue
    # (~26 round trips for status+outcome+sentiment+reason+direction
    # combined). Revisit with a partial/composite index if the calls table
    # grows large enough for this to show up in practice.

    async def total_count(self) -> int:
        """Every call, regardless of campaign or status."""
        result = await self.session.execute(select(func.count()).select_from(Call))
        return result.scalar_one()

    async def count_since(self, since: datetime) -> int:
        """Calls created at or after ``since`` (e.g. today's midnight)."""
        result = await self.session.execute(
            select(func.count()).select_from(Call).where(Call.created_at >= since)
        )
        return result.scalar_one()

    async def global_status_counts(self) -> list[tuple[CallLifecycleEnum, int]]:
        rows = await self.session.execute(
            select(Call.status, func.count()).group_by(Call.status)
        )
        return list(rows.all())

    async def global_outcome_counts(self) -> list[tuple[CallOutcomeEnum, int]]:
        rows = await self.session.execute(
            select(Call.outcome, func.count())
            .where(Call.outcome.is_not(None))
            .group_by(Call.outcome)
        )
        return list(rows.all())

    async def global_sentiment_counts(self) -> list[tuple[SentimentEnum, int]]:
        rows = await self.session.execute(
            select(Call.sentiment, func.count())
            .where(Call.sentiment.is_not(None))
            .group_by(Call.sentiment)
        )
        return list(rows.all())

    async def global_reason_category_counts(
        self,
    ) -> list[tuple[ReasonCategoryEnum, int]]:
        rows = await self.session.execute(
            select(Call.reason_category, func.count())
            .where(Call.reason_category.is_not(None))
            .group_by(Call.reason_category)
        )
        return list(rows.all())

    async def global_direction_counts(self) -> list[tuple[CallDirectionEnum, int]]:
        rows = await self.session.execute(
            select(Call.direction, func.count()).group_by(Call.direction)
        )
        return list(rows.all())

    async def active_geo_counts(self) -> list[tuple[str | None, int, int]]:
        """``(country, campaign_count, call_count)`` for GEOs currently being
        called (VOAD-55 dashboard block): campaigns that are ``running``,
        joined through their calls to the client's ``country``. Counts every
        country a running campaign's clients belong to, not just calls
        presently mid-dial (``Call.status == calling``) — a paused-between-
        attempts call still belongs to an active campaign's GEO.
        """
        rows = await self.session.execute(
            select(
                Client.country,
                func.count(func.distinct(Campaign.id)),
                func.count(func.distinct(Call.id)),
            )
            .select_from(Call)
            .join(Campaign, Call.campaign_id == Campaign.id)
            .join(Client, Call.client_id == Client.id)
            .where(Campaign.status == CampaignStatusEnum.running)
            .group_by(Client.country)
            .order_by(func.count(func.distinct(Call.id)).desc())
        )
        return list(rows.all())

    async def top_campaigns_by_calls(self, limit: int = 5) -> list[tuple[int, int]]:
        """``(campaign_id, call_count)``, busiest campaigns first."""
        rows = await self.session.execute(
            select(Call.campaign_id, func.count())
            .where(Call.campaign_id.is_not(None))
            .group_by(Call.campaign_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
        return list(rows.all())

    async def avg_duration_seconds(self) -> float | None:
        """Average talk time across every attempt that actually connected.

        Averages over *every* connected ``CallAttempt`` (answered_at and
        ended_at both set), not just each call's latest one the way
        ``Call.duration_seconds`` does — a window-function query to match
        that exactly isn't worth it for one dashboard KPI. None when nothing
        has ever connected.
        """
        result = await self.session.execute(
            select(
                func.avg(
                    func.extract(
                        "epoch", CallAttempt.ended_at - CallAttempt.answered_at
                    )
                )
            ).where(
                CallAttempt.answered_at.is_not(None), CallAttempt.ended_at.is_not(None)
            )
        )
        value = result.scalar_one_or_none()
        return float(value) if value is not None else None

    # -- dashboard trend (extends VOAD-38) -----------------------------------
    # These two combine what would otherwise be 4 separate round trips
    # (total_count, count_since, avg_duration_seconds, a new answer_rate)
    # into 2 — see the dashboard plan's "round trip" fix. They intentionally
    # duplicate total_count/count_since rather than replace them:
    # total_count is also used by /calls/stats/summary, which has no reason
    # to pull in a second, unrelated aggregate just to share one query.

    async def headline_counts(self, since: datetime) -> tuple[int, int]:
        """``(total, today)`` in one round trip."""
        result = await self.session.execute(
            select(
                func.count(),
                func.count().filter(Call.created_at >= since),
            ).select_from(Call)
        )
        return result.one()

    async def success_headline_counts(self) -> tuple[int, int]:
        """``(total, successful)`` — a call counts as successful iff at least
        one SMS was sent to its client afterward (``Message.call_id``, not
        failed). This is the org's own definition of a "successful" call: the
        telephony outcome (``Call.status``) is a diagnostic, not the metric.
        """
        result = await self.session.execute(
            select(
                func.count(func.distinct(Call.id)),
                func.count(func.distinct(Message.call_id)),
            )
            .select_from(Call)
            .outerjoin(
                Message,
                (Message.call_id == Call.id)
                & (Message.status != MessageStatusEnum.failed),
            )
        )
        return result.one()

    async def attempt_headline_stats(self) -> tuple[float | None, float | None]:
        """``(avg_duration_seconds, answer_rate)`` in one round trip over
        ``CallAttempt``. ``answer_rate`` is the share of attempts that ever
        connected (``answered_at`` set) over every attempt ever dialed; None
        when nothing has been dialed yet.

        Not run concurrently with ``headline_counts`` via ``asyncio.gather``:
        both would share ``self.session``, and SQLAlchemy's ``AsyncSession``
        is not safe for concurrent ``execute()`` calls on one connection.
        """
        result = await self.session.execute(
            select(
                func.avg(
                    func.extract(
                        "epoch", CallAttempt.ended_at - CallAttempt.answered_at
                    )
                ).filter(
                    CallAttempt.answered_at.is_not(None),
                    CallAttempt.ended_at.is_not(None),
                ),
                func.count().filter(CallAttempt.answered_at.is_not(None)),
                func.count(),
            )
        )
        avg_duration, answered, total = result.one()
        answer_rate = (answered / total) if total else None
        return (float(avg_duration) if avg_duration is not None else None), answer_rate

    async def daily_counts(
        self, since: date, until: date
    ) -> list[tuple[date, int, int, int]]:
        """``(day, total, successful, unsuccessful)`` for ``since..until``
        inclusive, oldest first — the dashboard's calls-over-time trend.
        Grouped by ``Call.created_at``'s day. "successful" mirrors
        ``success_headline_counts``: at least one non-failed SMS followed the
        call, not the call's own telephony status.
        """
        day = func.date_trunc("day", Call.created_at).label("day")
        rows = await self.session.execute(
            select(
                day,
                func.count(func.distinct(Call.id)).label("total"),
                func.count(func.distinct(Message.call_id)).label("successful"),
            )
            .select_from(Call)
            .outerjoin(
                Message,
                (Message.call_id == Call.id)
                & (Message.status != MessageStatusEnum.failed),
            )
            .where(
                Call.created_at >= since,
                Call.created_at < until + timedelta(days=1),
            )
            .group_by(day)
            .order_by(day)
        )
        return [
            (
                row.day.date(),
                row.total,
                row.successful,
                max(0, row.total - row.successful),
            )
            for row in rows
        ]

    async def cancel(self, call_id: int) -> bool:
        """Cancel a call that is not mid-conversation.

        Guarded in SQL, not in Python: the worker may claim the attempt
        between our read and our write. Cancelable states: ``pending`` (no
        live attempt), or ``calling`` whose attempt is still ``queued`` — once
        an attempt is dialing, the leg exists at the carrier and cancel is no
        longer the API's call.

        Args:
            call_id: The call's id.

        Returns:
            True if the row was still cancelable and is now canceled.
        """
        attempts = await self.session.execute(
            update(CallAttempt)
            .where(
                CallAttempt.call_id == call_id,
                CallAttempt.status == CallStatusEnum.queued,
            )
            .values(status=CallStatusEnum.canceled)
        )
        cancelable = (CallLifecycleEnum.pending,) + (
            (CallLifecycleEnum.calling,) if attempts.rowcount else ()
        )
        updated = await self.update(
            Call.id == call_id,
            Call.status.in_(cancelable),
            data={"status": CallLifecycleEnum.canceled},
        )
        return bool(updated)

    async def set_tags(self, call_id: int, tags: list[str]) -> bool:
        """Replace a call's tags wholesale (VOAD-28).

        Validation already happened at the schema layer (``SCallTagsUpdate``);
        this is a plain column write.

        Args:
            call_id: The call's id.
            tags: The full replacement tag list (already-validated strings).

        Returns:
            True if a row was updated (i.e. the call exists).
        """
        updated = await self.update(Call.id == call_id, data={"tags": tags})
        return bool(updated)


class CallAttemptCRUD(CRUD[CallAttempt]):
    model = CallAttempt


#: Message statuses that count as "the SMS went out" (VOAD-80).
SMS_SENT_STATUSES = (MessageStatusEnum.sent, MessageStatusEnum.delivered)


async def mark_sms_sent(session, call_id: int) -> bool:
    """Make a call's outcome ``sms_sent`` once its SMS is confirmed.

    Called when a message reaches ``sent``/``delivered`` (send time and the
    delivery webhook). Only fixes up a call that is *already settled* — while
    it is still ``calling`` the settle step derives the outcome itself, and
    touching the attempt then would set ``outcome`` before analysis ran (the
    outcome doubles as the "analysis done" marker). Guarded UPDATEs only, so
    it is idempotent and safe to call from any replica:

    * the SMS must be a sent/delivered ``Message`` created during the *latest*
      attempt (an older attempt's SMS never colours a restarted call);
    * ``do_not_call`` is never overwritten;
    * a call waiting on a ``call_later`` callback becomes ``completed`` with
      no ``next_attempt_at`` — the SMS was the result, no callback is due.

    Does not commit. Returns True when the call row changed.
    """
    last = (
        await session.execute(
            select(CallAttempt.id, CallAttempt.created_at)
            .where(CallAttempt.call_id == call_id)
            .order_by(CallAttempt.seq.desc())
            .limit(1)
        )
    ).one_or_none()
    if last is None:
        return False
    sent = await session.scalar(
        select(
            exists().where(
                Message.call_id == call_id,
                Message.status.in_(SMS_SENT_STATUSES),
                Message.created_at >= last.created_at,
            )
        )
    )
    if not sent:
        return False

    not_dnc = or_(Call.outcome.is_(None), Call.outcome != CallOutcomeEnum.do_not_call)
    # Pending callback -> completed. Only call_later: other pending calls are
    # retries (or restarts) that this SMS says nothing about.
    await session.execute(
        update(Call)
        .where(
            Call.id == call_id,
            Call.status == CallLifecycleEnum.pending,
            Call.outcome == CallOutcomeEnum.call_later,
        )
        .values(
            status=CallLifecycleEnum.completed,
            next_attempt_at=None,
            is_callback=False,
        )
    )
    changed = await session.execute(
        update(Call)
        .where(
            Call.id == call_id,
            Call.status.in_((CallLifecycleEnum.completed, CallLifecycleEnum.exhausted)),
            not_dnc,
            or_(Call.outcome.is_(None), Call.outcome != CallOutcomeEnum.sms_sent),
        )
        .values(outcome=CallOutcomeEnum.sms_sent)
    )
    if not changed.rowcount:
        return False
    await session.execute(
        update(CallAttempt)
        .where(
            CallAttempt.id == last.id,
            or_(
                CallAttempt.outcome.is_(None),
                CallAttempt.outcome.not_in(
                    (CallOutcomeEnum.do_not_call, CallOutcomeEnum.sms_sent)
                ),
            ),
        )
        .values(outcome=CallOutcomeEnum.sms_sent)
    )
    return True
