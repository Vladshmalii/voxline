"""Campaign behavioural sections, stored as JSONB and validated here.

Same storage rule as the agent's engine sections: ``{}`` in the row means
"the defaults below", and a section gaining a knob is a pydantic default, not
a migration. Both models are pure — the dispatcher asks them questions, they
never touch the clock's owner or the database.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from src.common.enums.engine import CallStatusEnum


class PriorityInterval(BaseModel):
    """A sub-window of the calling day (VOAD-33) that earns priority dialing.

    Evaluated on the same local clock as the enclosing :class:`CallingHours`
    — the campaign's own timezone, or a per-call one derived from the
    client's country. A lead whose local time falls inside one of these earns
    a dial before leads that are merely inside the general window.
    """

    start: time
    end: time

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: time, info) -> time:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("priority interval end must be after its start")
        return value


class CallingHours(BaseModel):
    """When a campaign is allowed to make phones ring.

    Evaluated on the wall clock of ``timezone`` by default — the campaign's
    market, not the server's locale. Unset ``start``/``end`` means any time
    of day; ``weekdays`` uses Python's convention (0 = Monday).

    VOAD-33: a call's window is actually evaluated on the timezone derived
    from its client's country (``utils.timezone.country_to_timezone``), not
    this ``timezone`` field — callers pass that derived zone in explicitly
    via ``is_open``/``is_priority``'s ``timezone`` argument. ``timezone``
    remains the fallback for calls whose client has no resolvable country,
    which is also exactly the pre-VOAD-33 behavior for a campaign whose
    clients carry no country data at all.
    """

    timezone: str = "UTC"
    start: time | None = None
    end: time | None = None
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    #: Sub-windows, in the same evaluation timezone, that earn priority
    #: dialing over the rest of the open window. Empty means no priority
    #: tier — every open call is equally eligible, the pre-VOAD-33 behavior.
    priority_intervals: list[PriorityInterval] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    @field_validator("weekdays")
    @classmethod
    def _valid_weekdays(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("weekdays must not be empty — pause the campaign instead")
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekdays are 0 (Monday) through 6 (Sunday)")
        return sorted(set(value))

    def _local(self, now: datetime | None, timezone: str | None) -> datetime:
        zone = ZoneInfo(timezone or self.timezone)
        if now is None:
            return datetime.now(zone)
        if now.tzinfo is None:
            # dispatch.py's ``now`` is a naive ``datetime.now()``, matching
            # this codebase's naive-UTC DB-column convention (see
            # ``Call.next_attempt_at``) — treat it as UTC explicitly rather
            # than letting ``astimezone`` assume the *server's* local zone,
            # which silently miscomputes the window on a non-UTC host.
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        return now.astimezone(zone)

    def is_open(
        self, now: datetime | None = None, *, timezone: str | None = None
    ) -> bool:
        """Whether dialing is allowed right now (or at ``now``, for tests).

        Args:
            now: An aware datetime to evaluate instead of the current moment.
            timezone: An IANA zone to evaluate against instead of
                ``self.timezone`` — VOAD-33 passes the client's
                country-derived zone here, falling back to ``self.timezone``
                (the pre-VOAD-33 behavior) when there isn't one.

        Returns:
            True when the local weekday and time fall inside the window.
        """
        local = self._local(now, timezone)
        if local.weekday() not in self.weekdays:
            return False
        if self.start is not None and local.time() < self.start:
            return False
        return self.end is None or local.time() < self.end

    def is_priority(
        self, now: datetime | None = None, *, timezone: str | None = None
    ) -> bool:
        """Whether ``now`` falls inside one of ``priority_intervals``.

        Does not itself check the general window — callers that want "open
        and priority" call both, same ``now``/``timezone`` pair.

        Args:
            now: An aware datetime to evaluate instead of the current moment.
            timezone: Same meaning as in :meth:`is_open`.

        Returns:
            True when local time falls inside any configured interval.
        """
        if not self.priority_intervals:
            return False
        local_time = self._local(now, timezone).time()
        return any(
            interval.start <= local_time < interval.end
            for interval in self.priority_intervals
        )


class RetryPolicy(BaseModel):
    """What a failed attempt earns: another try later, or the end of the road.

    ``max_attempts`` counts every attempt including the first. A status with
    no delay here (completed, canceled) is not retried — a conversation that
    happened is done, and a cancel was somebody's decision.
    """

    max_attempts: int = Field(3, ge=1, le=20)
    busy_delay_seconds: int = Field(300, ge=0)
    no_answer_delay_seconds: int = Field(3600, ge=0)
    failed_delay_seconds: int = Field(1800, ge=0)

    def delay_for(self, status: CallStatusEnum) -> int | None:
        """Seconds until the next attempt for a terminal attempt status.

        Returns:
            The delay, or None when that status is not retryable.
        """
        return {
            CallStatusEnum.busy: self.busy_delay_seconds,
            CallStatusEnum.no_answer: self.no_answer_delay_seconds,
            # A decline is paced like an unanswered call; invalid_number has no
            # entry on purpose (never retried).
            CallStatusEnum.rejected: self.no_answer_delay_seconds,
            CallStatusEnum.failed: self.failed_delay_seconds,
        }.get(status)
