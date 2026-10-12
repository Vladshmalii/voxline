"""The person behind a phone number — the row calls point at.

Deliberately minimal: everything situational (bonuses, per-call facts) is
snapshotted on the call, so history stays reproducible while this row stays
current. Clients are upserted by normalized phone wherever a number enters the
system, which is what makes ``status`` (do-not-call etc.) hold across
campaigns instead of inside one.

``country``/``language``/``vip_status``/``last_deposit``/``last_active`` and
``segment`` are persistent, cross-campaign facts about the client (VOAD-32/33/
34), refreshed on upsert-by-phone. They are distinct from the same-named
per-call snapshot fields on ``Call``/``AudienceMember``, which stay pinned at
the moment a call or list entry was created. ``segment`` is a lead-temperature
label (cold/warm/hot); it has no bearing on ``status`` (do-not-call/blocked),
which alone gates whether the client may be dialed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.common.enums.campaign import ClientSegmentEnum, ClientStatusEnum
from src.core.db.models import BaseUUID
from src.core.db.models import Enum as SQL_Enum


class Client(BaseUUID):
    """One callable person, unique per normalized phone number."""

    __uuid_prefix__ = "clnt"

    #: Normalized ``+<digits>`` (``utils.phone.normalize_phone``).
    phone: Mapped[str]
    name: Mapped[str] = mapped_column(default="", server_default="")
    status: Mapped[ClientStatusEnum] = mapped_column(
        SQL_Enum(ClientStatusEnum), default=ClientStatusEnum.active
    )

    #: ISO-3166 country code or free text, whichever the upload provided —
    #: used by VOAD-33 to derive a calling-hours timezone.
    country: Mapped[str | None] = mapped_column(nullable=True)
    language: Mapped[str | None] = mapped_column(nullable=True)
    vip_status: Mapped[str | None] = mapped_column(nullable=True)
    last_deposit: Mapped[float | None] = mapped_column(nullable=True)
    last_active: Mapped[datetime | None] = mapped_column(nullable=True)
    segment: Mapped[ClientSegmentEnum | None] = mapped_column(
        SQL_Enum(ClientSegmentEnum), nullable=True
    )

    #: VOAD-68: per-client idle timeout. NULL falls back to the agent's
    #: ``idle_timeout_seconds``.
    idle_timeout_seconds: Mapped[int | None] = mapped_column(nullable=True)

    __table_args__ = (UniqueConstraint("phone"),)

    def __str__(self):
        return f"{self.phone} ({self.name})" if self.name else self.phone
