"""Twilio Programmable Messaging as an outbound SMS route.

One POST per message, to the same REST API the voice adapter dials through::

    POST {api_root}/2010-04-01/Accounts/{sid}/Messages.json
        To=+15551112222 & Body=… & (From=… | MessagingServiceSid=…)

Two ways to name the sender, and the choice is the organization's, not ours:
a bare ``From`` is one number, predictable and cheap to reason about; a
``MessagingServiceSid`` hands Twilio a pool it rotates across, which is what
carries opt-out handling and per-country sender rules with it. The config
accepts either; :meth:`send` prefers an explicit per-message sender, then the
pool, then the configured default.

Not implemented on purpose: receiving. Twilio delivers inbound SMS by webhook
to a URL this service does not expose, and the adapter contract says outbound
only rather than growing a method nothing answers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

import httpx
from loguru import logger

from src.common.enums.engine import MessageStatusEnum, MessagingAdapterEnum
from src.integrations.messaging.base import (
    BaseMessagingAdapter,
    CallbackVerdict,
    MessagingAdapters,
    MessagingCapabilities,
    MessagingConfig,
)
from src.utils.twilio import api_root, verify_signature

#: Seconds to wait on the REST call. A send is a request in a user's path
#: (an API caller is blocked on it), so it fails fast rather than hanging.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: What Twilio calls a message's fate, mapped to what we call it.
#: ``accepted``/``queued``/``sending`` are provisional and absent on purpose —
#: they carry no information our own row does not already have.
DISPOSITIONS: dict[str, MessageStatusEnum] = {
    "sent": MessageStatusEnum.sent,
    "delivered": MessageStatusEnum.delivered,
    "undelivered": MessageStatusEnum.undelivered,
    "failed": MessageStatusEnum.failed,
    "canceled": MessageStatusEnum.canceled,
    "cancelled": MessageStatusEnum.canceled,
}

#: Remaining uncertainties in the contract above.
PROTOCOL_ASSUMPTIONS: tuple[str, ...] = (
    "a 201 response means accepted for delivery, not delivered",
    "segment counting follows GSM-7/UCS-2 without the GSM-7 extension table",
)


class TwilioMessagingAdapter(BaseMessagingAdapter):
    """Outbound SMS through one organization's Twilio account."""

    protocol_assumptions = PROTOCOL_ASSUMPTIONS

    capabilities: MessagingCapabilities = MessagingCapabilities(
        segment_chars=160,
        unicode_segment_chars=70,
        supports_delivery_status=True,
        supports_alphanumeric_sender=True,
        supports_sender_pool=True,
    )

    @classmethod
    def from_config(cls, config: MessagingConfig) -> Self:
        """Build the route from an organization's messaging row.

        Recognised ``options``: ``region``/``edge`` (Twilio FQDN pinning),
        ``timeout`` (seconds to wait on the REST call).
        """
        return cls(config)

    def __init__(self, config: MessagingConfig) -> None:
        """Initialise the adapter. No I/O happens here.

        Args:
            config: The organization's messaging row.
        """
        self._config = config
        options = config.options
        # `or None` / `or DEFAULT` rather than plain gets: a cleared input in
        # a configuration form arrives as "" or null, and an empty region
        # would build "https://api..twilio.com" while float("") would raise
        # past the caller's handling.
        self._region: str | None = options.get("region") or None
        self._edge: str | None = options.get("edge") or None
        self._timeout: float = float(options.get("timeout") or DEFAULT_TIMEOUT_SECONDS)

    async def send(
        self,
        *,
        to: str,
        body: str,
        sender: str | None = None,
        status_url: str | None = None,
    ) -> str:
        """Hand one SMS to Twilio.

        Args:
            to: Destination number, E.164.
            body: The message text, final.
            sender: Overrides the configured sender for this message.
            status_url: Twilio status callback for delivery dispositions.

        Returns:
            The message SID.

        Raises:
            ValueError: If credentials or a sender are missing.
            httpx.HTTPStatusError: If Twilio rejects the message.
        """
        account_id, auth_token = self._require_credentials()

        data = {"To": to, "Body": body}
        from_value = sender or self._config.sender
        if from_value:
            data["From"] = from_value
        elif self._config.sender_pool_id:
            data["MessagingServiceSid"] = self._config.sender_pool_id
        else:
            raise ValueError("twilio send needs a sender or a sender_pool_id")
        if status_url:
            data["StatusCallback"] = status_url

        root = api_root(self._config.control_url, region=self._region, edge=self._edge)
        async with httpx.AsyncClient(
            auth=(account_id, auth_token), timeout=self._timeout
        ) as client:
            response = await client.post(
                f"{root}/2010-04-01/Accounts/{account_id}/Messages.json", data=data
            )
            response.raise_for_status()
            message_sid = response.json()["sid"]
        logger.info(
            f"twilio sms to {to}: accepted as {message_sid} "
            f"({self.segments(body)} segment(s))"
        )
        return message_sid

    def verify_callback(
        self,
        *,
        url: str | None,
        headers: Mapping[str, str],
        form: dict[str, str] | None,
    ) -> bool:
        """Hold Twilio to its ``X-Twilio-Signature``.

        The signature is the only authentication an inbound Twilio request
        carries that covers the *parameters* — our own URL HMAC covers the URL
        alone, so a captured URL replayed with a rewritten ``MessageStatus``
        passes that and must fail here.

        Args:
            url: The status URL as Twilio was given it. None when no public
                base is configured, which is refused rather than waved
                through — behind an ingress the request's own URL is the
                internal address, which Twilio never saw and never signed.
            headers: The request's headers.
            form: The POST form; the signature covers it.

        Returns:
            True only for a signature this account could have produced.
        """
        if url is None:
            logger.error(
                "twilio callback: cannot verify the signature, no status_url_base "
                "on the messaging row and no CALL_WORKER__MEDIA_URL"
            )
            return False
        return verify_signature(
            self._config.auth_token or "",
            url,
            form,
            headers.get("X-Twilio-Signature"),
        )

    def parse_callback(
        self, payload: Any, *, provider_ref: str | None = None
    ) -> CallbackVerdict:
        """Read one Twilio status callback.

        Args:
            payload: The decoded form (or JSON, for a test double).
            provider_ref: The message SID we recorded at send time. A callback
                naming a different one is not ours and is dropped.

        Returns:
            The verdict; ``status`` is None for a provisional disposition.
        """
        if not isinstance(payload, Mapping):
            return CallbackVerdict()

        sid = payload.get("MessageSid") or payload.get("message_sid")
        if provider_ref and sid and str(sid) != provider_ref:
            logger.warning(
                f"twilio callback names {sid}, but this URL addresses {provider_ref}"
            )
            return CallbackVerdict()

        raw = str(
            payload.get("MessageStatus") or payload.get("message_status") or ""
        ).lower()
        status = DISPOSITIONS.get(raw)
        if status is None:
            return CallbackVerdict()

        code = payload.get("ErrorCode") or payload.get("error_code")
        text = payload.get("ErrorMessage") or payload.get("error_message")
        error = f"{code or ''} {text or ''}".strip() or None
        return CallbackVerdict(status=status, error=error)

    def _require_credentials(self) -> tuple[str, str]:
        if not (self._config.account_id and self._config.auth_token):
            raise ValueError("twilio send needs account_id and auth_token")
        return self._config.account_id, self._config.auth_token


MessagingAdapters[MessagingAdapterEnum.twilio] = TwilioMessagingAdapter
