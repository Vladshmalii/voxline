"""Billing and balance management for tenant organizations."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db.models import Base, BaseUUID
from src.models.call import Call
from src.models.messaging import Message


class OrganizationBalance(Base):
    """Independent call and SMS balances, with their respective tariffs."""

    currency: Mapped[str] = mapped_column(
        String(10), default="USD", server_default="USD"
    )
    call_balance: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    sms_balance: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    cost_per_minute: Mapped[float] = mapped_column(
        Float, default=0.10, server_default="0.10"
    )
    cost_per_sms: Mapped[float] = mapped_column(
        Float, default=0.02, server_default="0.02"
    )
    # Per-minute clients: the organization pays for minutes only, so the whole
    # billing section is closed to its non-admin users (UI and API alike).
    minutes_only: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class BalanceTransaction(BaseUUID):
    """One financial operation: deposit, call charge, sms charge, or adjustment."""

    __uuid_prefix__ = "tx"

    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # Types: "deposit", "call_usage", "sms_usage", "adjustment", "refund"
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(8), default="calls", server_default="calls"
    )
    description: Mapped[str] = mapped_column(Text, default="", server_default="")

    call_id: Mapped[int | None] = mapped_column(
        ForeignKey(Call.id, ondelete="SET NULL"), nullable=True
    )
    call: Mapped[Call | None] = relationship()

    sms_id: Mapped[int | None] = mapped_column(
        ForeignKey(Message.id, ondelete="SET NULL"), nullable=True
    )
    sms: Mapped[Message | None] = relationship()

    admin_id: Mapped[int | None] = mapped_column(nullable=True)
    balance_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Retained for rows created before the accounts were split. It describes
    # the historical shared account, never either account's new balance.
    legacy_balance_after: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "channel IN ('calls', 'sms')", name="ck_balancetransaction_channel"
        ),
        Index("ix_balancetransaction_channel_created_at", "channel", "created_at"),
    )
