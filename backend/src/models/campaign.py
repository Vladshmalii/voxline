"""A campaign: the *what for* of outbound calling.

Split from the agent on purpose — the agent is how the org speaks (voice,
models, turn-taking), the campaign is what this batch of calls is for: the
script, the period, the retry posture. ``call_script`` is a Jinja template
rendered per attempt in a sandbox with ``name``, ``bonuses`` and
``attributes`` (see ``utils/script.py``).

``calling_hours`` and ``retry`` are JSONB sections validated through
:mod:`src.schemas.campaign`; ``{}`` means the section's defaults. The
dispatcher owns the automatic transitions (``scheduled → running`` at
``starts_at``, ``running → completed`` at ``ends_at`` or when nothing is left
to dial); operators own the rest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.enums.campaign import CampaignStatusEnum
from src.core.db.models import BaseUUID
from src.core.db.models import Enum as SQL_Enum
from src.models.agent import VoiceAgent


class Campaign(BaseUUID):
    """One batch of outbound calls with a shared purpose and pace."""

    __uuid_prefix__ = "cmpn"

    name: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[CampaignStatusEnum] = mapped_column(
        SQL_Enum(CampaignStatusEnum), default=CampaignStatusEnum.draft
    )

    #: RESTRICT: a campaign without its agent is undialable, refuse the delete.
    agent_id: Mapped[int] = mapped_column(
        ForeignKey(VoiceAgent.id, ondelete="RESTRICT")
    )
    agent: Mapped[VoiceAgent] = relationship(lazy="joined")

    call_script: Mapped[str] = mapped_column(Text, default="", server_default="")

    #: NULL starts_at: starts when the operator says so. NULL ends_at: runs
    #: until out of calls or completed by hand.
    starts_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(nullable=True)

    calling_hours: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    retry: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )

    #: Hidden from the default list without deleting it — unlike delete
    #: (refused once a call exists, ``Call.campaign_id``'s RESTRICT), archiving
    #: never touches call history. The service refuses to archive a `running`
    #: campaign; nothing else in the app treats this specially (the
    #: dispatcher only ever looks at `status`).
    is_archived: Mapped[bool] = mapped_column(default=False, server_default="false")

    def __str__(self):
        return f"{self.name} [{self.status}]"
