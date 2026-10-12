"""The organization's telephony binding — the row behind ``TelephonyConfig``.

One row per carrier account (Twilio credentials, a jambonz/SIP-bridge control
endpoint). Kept separate from the agent because the leg is not the
conversation: several agents typically dial out through one trunk, and
swapping carriers must not touch agent configuration.

Maps 1:1 to :class:`src.integrations.telephony.base.TelephonyConfig`, which is
what a repository builds from this row for the worker.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.models import Base


class Telephony(Base):
    """One carrier or bridge account an agent can place calls through."""

    name: Mapped[str]
    #: Registry key — a ``TelephonyAdapterEnum`` value. A string for the same
    #: reason ``Model.adapter`` is one: the registry validates it loudly, and
    #: a new carrier is already a code release without an ALTER TYPE on top.
    adapter: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default="false", default=False)

    #: Provider account identifier (Twilio Account SID, a bridge tenant id).
    account_id: Mapped[str | None] = mapped_column(nullable=True)
    #: Provider secret (Twilio auth token, a bridge bearer token).
    auth_token: Mapped[str | None] = mapped_column(nullable=True)
    #: Default outbound caller id, overridable per dial.
    caller_id: Mapped[str | None] = mapped_column(nullable=True)
    #: Control-API root. None means the provider's public default; a
    #: self-hosted bridge (jambonz) or a Twilio-compatible double sets it.
    control_url: Mapped[str | None] = mapped_column(nullable=True)

    #: Overrides for the adapter's ``TelephonyCapabilities`` — wire behaviour
    #: (codec, sample rate, start-event expectations) as data, so a bridge
    #: that ships PCM16 at 16 kHz is a row change, not a release.
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    #: Adapter extras not worth a column: region/edge pinning, timeouts.
    options: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )

    def __str__(self):
        return f"{self.adapter}:{self.name}"
