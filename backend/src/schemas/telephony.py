"""The telephony binding schema — one organization's carrier account.

Relocated from ``src/integrations/telephony/base.py`` (every pydantic schema
lives under ``src/schemas``); the telephony package re-exports it and owns the
adapter contract that consumes it. Plain pydantic, no environment reads: the
worker builds it from the organization's rows, a test builds it inline, and
the adapter cannot tell the difference.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.common.enums.engine import TelephonyAdapterEnum


class TelephonyConfig(BaseModel):
    """One organization's telephony binding — everything an adapter is built from.

    Credentials are per organization — two organizations on Twilio are two
    accounts — so adapters, like every other client in the platform, are per
    call and never shared.
    """

    adapter: TelephonyAdapterEnum
    #: Provider account identifier (Twilio's Account SID, a bridge tenant id).
    account_id: str | None = None
    #: Provider secret (Twilio auth token, a bridge bearer token).
    auth_token: str | None = None
    #: Default outbound caller id, overridable per dial.
    caller_id: str | None = None
    #: Control-API root. None means the provider's public default (Twilio's
    #: cloud); a self-hosted bridge or a Twilio-compatible test double sets it.
    control_url: str | None = None
    #: Overrides for the adapter's ``TelephonyCapabilities``, applied by
    #: ``build_telephony()``. Data, so an operator can correct a deployment
    #: without a release.
    capabilities: dict[str, Any] = Field(default_factory=dict)
    #: Anything the adapter accepts that is not worth a column: region/edge
    #: pinning, session timeouts, handshake timeouts, a codec under test.
    options: dict[str, Any] = Field(default_factory=dict)
