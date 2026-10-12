"""The organization's messaging binding — the row behind ``MessagingConfig``.

One row per SMS account. Kept separate from :class:`~src.models.telephony.Telephony`
rather than folded into it: an organization's voice trunk and its SMS route
are separate commercial arrangements (often separate vendors, always separate
numbers and pricing), and the self-hosted SIP bridge that carries calls
carries no text at all. Merging them would make every bridge row carry four
columns it can never fill.

Maps 1:1 to :class:`src.schemas.messaging.MessagingConfig`, which is what
:class:`~src.repositories.messaging.MessagingCRUD` builds from this row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums.engine import MessageStatusEnum
from src.core.db.models import Base, BaseUUID
from src.core.db.models import Enum as SQL_Enum
from src.models.call import Call


class Messaging(Base):
    """One SMS account an organization can send through."""

    name: Mapped[str]
    #: Registry key — a ``MessagingAdapterEnum`` value. A string for the same
    #: reason ``Telephony.adapter`` is one: the registry validates it loudly,
    #: and a new vendor is already a release without an ALTER TYPE on top.
    adapter: Mapped[str]
    #: Only one row per organization may be active; the send path resolves the
    #: route by this flag when the caller names none.
    is_active: Mapped[bool] = mapped_column(server_default="false", default=False)

    #: Provider account identifier (Twilio Account SID).
    account_id: Mapped[str | None] = mapped_column(nullable=True)
    #: Provider secret (Twilio auth token).
    auth_token: Mapped[str | None] = mapped_column(nullable=True)
    #: Default sender — an E.164 number or an alphanumeric sender id.
    sender: Mapped[str | None] = mapped_column(nullable=True)
    #: Provider-side sender pool (Twilio Messaging Service SID), used when no
    #: explicit sender is given.
    sender_pool_id: Mapped[str | None] = mapped_column(nullable=True)
    #: Control-API root. None means the provider's public default.
    control_url: Mapped[str | None] = mapped_column(nullable=True)

    #: Overrides for the adapter's ``MessagingCapabilities`` — segment sizes,
    #: what the account is actually allowed to do — as data, so a route whose
    #: destinations refuse alphanumeric senders is a row change.
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    #: Adapter extras not worth a column: region/edge pinning, timeouts, and
    #: ``status_url_base`` — the public base a delivery callback should come
    #: back to, when it differs from the call worker's media URL.
    options: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )

    def __str__(self):
        return f"{self.adapter}:{self.name}"


class Message(BaseUUID):
    """One outbound SMS, from accepted to its carrier verdict.

    The row exists because the verdict arrives *later* than the response to
    the send: the provider acknowledges in the HTTP call, the carrier reports
    delivery by webhook seconds or minutes afterwards, long after the API
    caller is gone. Without a row there is nothing for that callback to
    update, which is why delivery status and storage are one feature, not two.

    Addressed by uuid, like a call attempt: the status URL carries the uuid
    and an HMAC of it, so any hooks replica can answer without a lookup.

    Outbound only. Nothing writes an inbound message here.
    """

    __uuid_prefix__ = "msg"

    #: RESTRICT: the row records which account and sender were billed, and a
    #: send history that cannot say which route sent it is not a record.
    messaging_id: Mapped[int] = mapped_column(
        ForeignKey(Messaging.id, ondelete="RESTRICT")
    )

    #: The call this SMS was sent from, when sent via the in-call "send_sms"
    #: tool — NULL for messages sent any other way (e.g. a manual/API send
    #: with no call context). SET NULL: a call's history outlives no message,
    #: but a message's billing record must survive the call being purged.
    #: This is the only link between a call and the SMS it triggered — stats
    #: that define call "success" as "a follow-up SMS was sent" join through
    #: this column, see ``CallCRUD``.
    call_id: Mapped[int | None] = mapped_column(
        ForeignKey(Call.id, ondelete="SET NULL"), nullable=True
    )

    #: Destination, normalized to E.164 before the send. Named like
    #: ``Call.from_number`` — and ``to`` alone is a reserved SQL word.
    to_number: Mapped[str]
    #: The sender as handed to the provider — a number, an alphanumeric id, or
    #: NULL when a sender pool chose it and we never learned which number.
    sender: Mapped[str | None] = mapped_column(nullable=True)
    body: Mapped[str] = mapped_column(Text)
    #: Billable segments, as counted at send time from the adapter's declared
    #: capabilities. Stored rather than recomputed: the capability row may
    #: change, the invoice will not.
    segments: Mapped[int] = mapped_column(default=1, server_default="1")

    status: Mapped[MessageStatusEnum] = mapped_column(
        SQL_Enum(MessageStatusEnum), default=MessageStatusEnum.queued
    )
    #: The provider's reference (Twilio message SID) — what reconciles this
    #: row against the vendor's logs, and what its callbacks name.
    provider_ref: Mapped[str | None] = mapped_column(nullable=True)
    #: Why it failed, in the provider's words plus its error code when given.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: When the provider accepted it, and when the carrier reported a verdict.
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_message_status", "status"),
        Index("ix_message_to_number", "to_number"),
        Index("ix_message_provider_ref", "provider_ref"),
        Index("ix_message_call_id", "call_id"),
        Index("ix_message_created_at", "created_at"),
    )

    def __str__(self):
        return f"sms to {self.to_number} [{self.status}]"
