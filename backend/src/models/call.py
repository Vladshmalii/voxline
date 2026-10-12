"""Call and CallAttempt: the assignment, and the legs made for it.

``Call`` is *who to reach and with what*: the client, the campaign, and the
script inputs (``bonuses``, ``attributes``) pinned at creation so every
attempt renders the same call the same way. ``CallAttempt`` is one
dial-to-hangup leg with its own status machine, transcript and provider
reference — a retry is a **new attempt row**, never an overwrite of a leg
that already happened.

The dispatcher (``worker/dispatch.py``) moves the parent: it claims due
``pending`` rows, spawns an attempt, and later settles ``calling`` parents
whose latest attempt reached a terminal status — back to ``pending`` with a
``next_attempt_at`` (retry) or forward to a terminal lifecycle state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.enums.campaign import (
    CallLifecycleEnum,
    CallOutcomeEnum,
    ReasonCategoryEnum,
    SentimentEnum,
)
from src.common.enums.engine import CallDirectionEnum, CallStatusEnum
from src.core.db.models import BaseUUID
from src.core.db.models import Enum as SQL_Enum
from src.models.agent import VoiceAgent
from src.models.campaign import Campaign
from src.models.client import Client


class Call(BaseUUID):
    """One assignment: reach this client, for this campaign, with these facts."""

    __uuid_prefix__ = "call"

    #: RESTRICT: the dialed number lives only on the client row, and call
    #: history without its number is no record at all.
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey(Client.id, ondelete="RESTRICT"), nullable=True
    )
    client: Mapped[Client | None] = relationship(lazy="joined")

    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey(Campaign.id, ondelete="RESTRICT"), nullable=True
    )
    campaign: Mapped[Campaign | None] = relationship(lazy="joined")

    #: SET NULL: history outlives the agent that made it.
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey(VoiceAgent.id, ondelete="SET NULL"), nullable=True
    )
    agent: Mapped[VoiceAgent | None] = relationship()

    direction: Mapped[CallDirectionEnum] = mapped_column(
        SQL_Enum(CallDirectionEnum), default=CallDirectionEnum.outbound
    )
    status: Mapped[CallLifecycleEnum] = mapped_column(
        SQL_Enum(CallLifecycleEnum), default=CallLifecycleEnum.pending
    )

    from_number: Mapped[str | None] = mapped_column(nullable=True)
    language: Mapped[str | None] = mapped_column(nullable=True)

    #: Script inputs, pinned at creation: the offers available to this client
    #: and the per-call facts. Every attempt renders from these same values.
    bonuses: Mapped[list[Any]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list
    )
    player_id: Mapped[str | None] = mapped_column(nullable=True)
    vip_status: Mapped[str | None] = mapped_column(nullable=True)
    last_deposit: Mapped[float | None] = mapped_column(nullable=True)
    last_active: Mapped[datetime | None] = mapped_column(nullable=True)
    country: Mapped[str | None] = mapped_column(nullable=True)
    timezone: Mapped[str | None] = mapped_column(nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    #: Per-call config overrides (``CallContext.overrides``), stored verbatim
    #: so an A/B run or a support reproduction is readable from the row.
    overrides: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )

    attempts_made: Mapped[int] = mapped_column(default=0, server_default="0")
    #: ``attempts_made`` at the last campaign restart. Attempt ``seq`` keeps
    #: counting from ``attempts_made`` (UNIQUE(call_id, seq)); the retry budget
    #: is ``attempts_made - attempt_base``.
    attempt_base: Mapped[int] = mapped_column(default=0, server_default="0")
    #: NULL means "as soon as allowed"; set by the settle step for retries.
    next_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_callback: Mapped[bool] = mapped_column(default=False, server_default="false")
    #: Latest business result, copied from the attempt at settle for listings.
    outcome: Mapped[CallOutcomeEnum | None] = mapped_column(
        SQL_Enum(CallOutcomeEnum), nullable=True
    )
    #: Which entry of ``bonuses`` the customer accepted, if any — copied from
    #: the attempt at settle, same as ``outcome``. Free text because the set
    #: of offers is per-campaign data, not a fixed enum.
    selected_offer: Mapped[str | None] = mapped_column(nullable=True)
    sentiment: Mapped[SentimentEnum | None] = mapped_column(
        SQL_Enum(SentimentEnum), nullable=True
    )
    reason_category: Mapped[ReasonCategoryEnum | None] = mapped_column(
        SQL_Enum(ReasonCategoryEnum), nullable=True
    )
    #: Free-text labels (VOAD-28), not a fixed enum on purpose — the v1 set
    #: ("Клиент не ответил", "Клиент ответил", "Разговор завершён",
    #: "Отказался от дальнейших звонков") is validated at the API layer, so a
    #: future tag is a validator change, not a migration. Copied from the
    #: latest attempt at settle, same as outcome/sentiment/reason_category.
    tags: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSONB), default=list)

    attempts: Mapped[list[CallAttempt]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CallAttempt.seq",
    )

    __table_args__ = (
        # The dispatcher's claim query: pending rows whose time has come.
        Index("ix_call_due", "status", "next_attempt_at"),
        Index("ix_call_campaign_id", "campaign_id"),
        Index("ix_call_client_id", "client_id"),
        # The dashboard's trend query (StatsService.timeseries/headline_counts)
        # filters/groups by this column.
        Index("ix_call_created_at", "created_at"),
    )

    @property
    def duration_seconds(self) -> int | None:
        """Duration of the latest attempt — what a call list shows."""
        if not self.attempts:
            return None
        latest = self.attempts[-1]
        if latest.answered_at is None or latest.ended_at is None:
            return None
        return max(0, int((latest.ended_at - latest.answered_at).total_seconds()))

    def __str__(self):
        return f"call {self.id} [{self.status}]"


class CallAttempt(BaseUUID):
    """One leg, dial to hangup — the row the worker and hooks service write."""

    __uuid_prefix__ = "catt"

    call_id: Mapped[int] = mapped_column(ForeignKey(Call.id, ondelete="CASCADE"))
    call: Mapped[Call] = relationship(back_populates="attempts", lazy="joined")

    #: 1-based attempt index within the call.
    seq: Mapped[int]

    status: Mapped[CallStatusEnum] = mapped_column(
        SQL_Enum(CallStatusEnum), default=CallStatusEnum.queued
    )

    #: Language the leg was routed with; the transcript records switches.
    language: Mapped[str | None] = mapped_column(nullable=True)

    #: The carrier's reference (jambonz/Twilio call sid) — what reconciles our
    #: record against the partner's CDRs, and what hangup needs.
    provider_ref: Mapped[str | None] = mapped_column(nullable=True)

    #: ``ResolvedProfile.summary()`` at attempt start — the first thing to
    #: read when a call misbehaves, preserved even if config changed since.
    profile_summary: Mapped[str | None] = mapped_column(nullable=True)

    #: The conversation as delivered: interruption truncation already applied,
    #: so this is what the caller heard, not what the model wrote.
    messages: Mapped[list[Any]] = mapped_column(
        MutableList.as_mutable(JSONB), default=list
    )

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The provider's own verdict as reported on the status webhook (jambonz
    #: ``call_status`` / Twilio ``CallStatus``) and its SIP code + reason, kept
    #: verbatim so "why did this call not connect" is answerable from the row.
    provider_status: Mapped[str | None] = mapped_column(nullable=True)
    provider_reason: Mapped[str | None] = mapped_column(nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # -- post-call analysis (services/analysis.py, run by the worker).
    # outcome doubles as the "analysis done" marker: completed attempts with
    # messages and a NULL outcome are (re-)enqueued for analysis each tick,
    # judged stale by ended_at alone.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[CallOutcomeEnum | None] = mapped_column(
        SQL_Enum(CallOutcomeEnum), nullable=True
    )
    #: Which entry of ``Call.bonuses`` the model judged the customer accepted;
    #: NULL when none was, or the transcript named something off the list.
    selected_offer: Mapped[str | None] = mapped_column(nullable=True)
    sentiment: Mapped[SentimentEnum | None] = mapped_column(
        SQL_Enum(SentimentEnum), nullable=True
    )
    reason_category: Mapped[ReasonCategoryEnum | None] = mapped_column(
        SQL_Enum(ReasonCategoryEnum), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    #: Where the leg's audio recording can be fetched from (VOAD-37); NULL for
    #: a leg that never connected, or before the engine started persisting one.
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("call_id", "seq"),
        # The worker claims queued rows; the sweep scans by status.
        Index("ix_callattempt_status", "status"),
        Index("ix_callattempt_call_id", "call_id"),
    )

    def __str__(self):
        return f"attempt {self.seq} of call {self.call_id} [{self.status}]"
