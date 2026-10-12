"""The messaging binding schema — one organization's SMS account.

Sibling of :mod:`src.schemas.telephony`, deliberately not the same object: an
organization's voice trunk and its SMS route are separate commercial
arrangements, often with separate vendors, and a SIP bridge that carries calls
carries no text at all. Plain pydantic, no environment reads: a repository
builds it from the organization's row, a test builds it inline, and the
adapter cannot tell the difference.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.common.enums.engine import MessagingAdapterEnum


class MessagingConfig(BaseModel):
    """One organization's SMS binding — everything an adapter is built from."""

    adapter: MessagingAdapterEnum
    #: Provider account identifier (Twilio's Account SID).
    account_id: str | None = None
    #: Provider secret (Twilio auth token).
    auth_token: str | None = None
    #: Default sender, overridable per message: an E.164 number, or an
    #: alphanumeric sender id where the destination country allows one.
    sender: str | None = None
    #: Provider-side sender pool. Twilio calls it a Messaging Service SID and
    #: prefers it over a bare ``From`` — it owns the number pool, the opt-out
    #: handling and the per-country compliance rules. Set it *or* ``sender``.
    sender_pool_id: str | None = None
    #: Control-API root. None means the provider's public default; a
    #: Twilio-compatible test double or a region-pinned deployment sets it.
    control_url: str | None = None
    #: Overrides for the adapter's ``MessagingCapabilities``, applied by
    #: ``build_messaging()``. Data, so an operator can correct a deployment
    #: without a release.
    capabilities: dict[str, Any] = Field(default_factory=dict)
    #: Anything the adapter accepts that is not worth a column: region/edge
    #: pinning, request timeouts.
    options: dict[str, Any] = Field(default_factory=dict)
