"""Audience: a reusable, named list of contacts, independent of any campaign.

A campaign's calls are still created by ``CampaignService.upload`` — an
audience is just another source of the same rows (``AudienceMember`` mirrors
``SCampaignContactRow``), so adding an audience to a campaign reuses the exact
per-row validation and duplicate handling that a direct CSV/JSON upload does.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db.models import BaseUUID
from src.models.client import Client


class Audience(BaseUUID):
    """A named, reusable list — the campaign it feeds is chosen later, and
    can change."""

    __uuid_prefix__ = "aud"

    name: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: Hidden from the default list without deleting its members' history —
    #: unlike DELETE /audiences/{id}, which removes the row (and its
    #: AudienceMember rows via cascade) outright.
    is_archived: Mapped[bool] = mapped_column(default=False, server_default="false")

    def __str__(self):
        return self.name


class AudienceMember(BaseUUID):
    """One client on one audience, with the script inputs this list carries
    for them — the same shape ``Call`` pins at creation."""

    __uuid_prefix__ = "audm"

    audience_id: Mapped[int] = mapped_column(
        ForeignKey(Audience.id, ondelete="CASCADE")
    )
    audience: Mapped[Audience] = relationship()

    client_id: Mapped[int] = mapped_column(ForeignKey(Client.id, ondelete="RESTRICT"))
    client: Mapped[Client] = relationship(lazy="joined")

    language: Mapped[str | None] = mapped_column(nullable=True)
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

    __table_args__ = (
        UniqueConstraint("audience_id", "client_id"),
        Index("ix_audiencemember_audience_id", "audience_id"),
    )

    def __str__(self):
        return f"{self.client.phone} in audience {self.audience_id}"


class AudienceUpload(BaseUUID):
    """One CSV/JSON upload event — who, when, and how it scored (VOAD-34's
    "История загрузок"). Covers both an audience-targeted upload and the
    status-segment client import (VOAD-32), which is why ``audience_id`` is
    nullable: the latter has no single audience to point at.
    """

    __uuid_prefix__ = "audup"

    audience_id: Mapped[int | None] = mapped_column(
        ForeignKey(Audience.id, ondelete="SET NULL"), nullable=True
    )
    audience: Mapped[Audience | None] = relationship()

    #: control-database user id from the JWT (``SAuthUser.id``); no local
    #: user table to join against.
    uploaded_by: Mapped[int] = mapped_column()
    filename: Mapped[str] = mapped_column(default="", server_default="")
    total_rows: Mapped[int] = mapped_column(default=0, server_default="0")
    valid_rows: Mapped[int] = mapped_column(default=0, server_default="0")
    invalid_rows: Mapped[int] = mapped_column(default=0, server_default="0")

    def __str__(self):
        return f"upload {self.id} ({self.valid_rows}/{self.total_rows} valid)"
