"""Mamonty as an outbound SMS route.

One POST per message, JSON, with the API key in the body rather than a header::

    POST {api_root}/apiSms/create
        {"apiKey": …, "sms": [{"channel": …, "phone": …, "text": …, "sender": …}]}

Mamonty is a multi-channel aggregator — the same endpoint reaches Viber, VK,
WhatsApp and Telegram, and can run cascades that fall back between them. This
adapter speaks **SMS only**, which is the pair of channels that reach a
handset's message inbox:

``digit``
    Delivered from a numeric short code. No sender name to agree with the
    operator, and none is accepted.
``char``
    Delivered from an alphanumeric sender id ("VIRTA"), which the provider
    registers in advance. The sender is mandatory.

Everything else the vendor offers is out of scope on purpose rather than
half-implemented: a messenger message is not a body of text with a destination,
it is a template id, a button, an image hash and a per-channel lifetime, and
the adapter contract has nowhere to put any of that.

Delivery status comes back to the ``webhookUrl`` handed over with the send. The
API instruction's "Receiving SMS statuses via Webhook" section is a heading with
no body, so the contract below was established by pointing a capture server at a
tunnel and reading what actually arrived::

    POST <the webhookUrl, path and query intact>
    Content-Type: application/json

    [{"id": 313913312, "status": "error", "phone": "359899004167",
      "cost": 0.0, "error_description": "Routing error",
      "created_at": 1790079468, "updated_at": 1790079474}]

Three things that shape the parser:

* the body is a **list** — the provider batches several messages into one call,
  so a verdict has to be picked out by id rather than assumed to be the only
  one;
* the fields are snake_case (``error_description``), where the REST API spells
  the same things camelCase (``errorDescription``). One vendor, two dialects;
* nothing is signed. The only non-standard headers are the vendor's own Sentry
  tracing. The HMAC our status URL carries is therefore the whole lock, which
  is why the URL's path and query surviving the round trip was worth checking.

Observed and not relied upon: a callback also arrived for a message sent from
the vendor's own panel, addressed to the bare base URL with no path. Ours are
mounted under a per-message path, so such a call finds nothing and 404s, which
is the correct outcome — but it is the reason the parser confirms the id
instead of trusting whatever a batch happens to contain.
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

#: Mamonty's public API root; a ``control_url`` overrides it.
MAMONTY_API_ROOT = "https://admin.mamonty.com"

#: Seconds to wait on the REST call. Same reasoning as Twilio's: a send sits in
#: an API caller's request path, so it fails fast rather than hanging.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: The channels that reach a handset as an SMS. The vendor's other channels
#: (``viber``, ``vk``, ``whatsapp``, ``telegram_auth``) need per-channel
#: parameters this contract cannot express, and are refused rather than sent
#: as something they are not.
SMS_CHANNELS = frozenset({"digit", "char"})

#: The channel that needs a registered sender name; the other refuses one.
ALPHANUMERIC_CHANNEL = "char"

#: What Mamonty calls a message's fate, mapped to what we call it. Taken from
#: the status table in the API instruction; ``created``, ``moderation`` and
#: ``planned`` are provisional and absent on purpose. ``read`` collapses into
#: ``delivered`` — it is strictly later, and we have no rank beyond delivered.
DISPOSITIONS: dict[str, MessageStatusEnum] = {
    "sent": MessageStatusEnum.sent,
    "delivered": MessageStatusEnum.delivered,
    "read": MessageStatusEnum.delivered,
    "not_delivered": MessageStatusEnum.undelivered,
    "error": MessageStatusEnum.failed,
    "low_balance": MessageStatusEnum.failed,
    "low_partner_balance": MessageStatusEnum.failed,
    "rejected": MessageStatusEnum.canceled,
}

#: Remaining uncertainties in the contract above.
PROTOCOL_ASSUMPTIONS: tuple[str, ...] = (
    "a success response means accepted for delivery, not delivered",
    (
        "the vendor documents phone numbers as 11 digits (russian); numbers "
        "for other countries are sent as their digits with the leading + removed"
    ),
    (
        "a refused message rides inside an envelope the vendor still calls a "
        "success, with HTTP 200; only the entry's own 'status' says otherwise"
    ),
    "segment counting follows GSM-7/UCS-2 without the GSM-7 extension table",
    (
        "the callback contract was observed on the wire, not documented; the "
        "vendor may change it without telling anyone"
    ),
)


class MamontyMessagingAdapter(BaseMessagingAdapter):
    """Outbound SMS through one organization's Mamonty account.

    The organization's messaging row maps on as: ``auth_token`` is the API key
    from the vendor's "API settings" page, ``sender`` is the registered sender
    name, ``control_url`` overrides the API root. ``account_id`` and
    ``sender_pool_id`` are unused — Mamonty authenticates with the key alone
    and has no sender pool to address.

    Delivery status is reported to the ``webhookUrl`` sent with each message;
    see the module docstring for the shape it comes back in.
    """

    protocol_assumptions = PROTOCOL_ASSUMPTIONS

    capabilities: MessagingCapabilities = MessagingCapabilities(
        segment_chars=160,
        unicode_segment_chars=70,
        supports_delivery_status=True,
        supports_alphanumeric_sender=True,
        supports_sender_pool=False,
    )

    @classmethod
    def from_config(cls, config: MessagingConfig) -> Self:
        """Build the route from an organization's messaging row.

        Recognised ``options``: ``channel`` (``digit`` or ``char``; inferred
        from whether a sender is configured when absent), ``timeout`` (seconds
        to wait on the REST call).

        Raises:
            ValueError: If ``channel`` names a channel this adapter does not
                speak. Raised here rather than mid-send so a row configured
                for Viber is refused when the route is resolved, naming the
                row — see ``MessagingService.send_sms``.
        """
        return cls(config)

    def __init__(self, config: MessagingConfig) -> None:
        """Initialise the adapter. No I/O happens here.

        Args:
            config: The organization's messaging row.

        Raises:
            ValueError: If ``options["channel"]`` is not an SMS channel.
        """
        self._config = config
        options = config.options
        # `or` rather than a default: a form that renders options as inputs
        # sends a cleared field as "" or null, and float("") is a TypeError
        # the caller does not catch — a blank box would 500 a send.
        self._timeout: float = float(options.get("timeout") or DEFAULT_TIMEOUT_SECONDS)

        channel = options.get("channel") or None
        if channel is not None and channel not in SMS_CHANNELS:
            raise ValueError(
                f"mamonty channel {channel!r} is not an SMS channel; "
                f"this adapter speaks {sorted(SMS_CHANNELS)}"
            )
        self._channel: str | None = channel

    async def send(
        self,
        *,
        to: str,
        body: str,
        sender: str | None = None,
        status_url: str | None = None,
    ) -> str:
        """Hand one SMS to Mamonty.

        Args:
            to: Destination number, E.164.
            body: The message text, final.
            sender: Overrides the configured sender for this message.
            status_url: Where the vendor should report this message's fate;
                sent as ``webhookUrl``. Its path and query survive the round
                trip, so the HMAC ours carries comes back with it.

        Returns:
            The vendor's ``smsId``, as a string.

        Raises:
            ValueError: If the API key or a sender is missing, or the provider
                answers with an application-level failure.
            httpx.HTTPStatusError: If Mamonty rejects the request outright.
        """
        api_key = self._require_api_key()
        from_value = sender or self._config.sender
        channel = self._channel or (ALPHANUMERIC_CHANNEL if from_value else "digit")

        message: dict[str, Any] = {
            "channel": channel,
            # The vendor's examples are bare digits, never E.164.
            "phone": to.lstrip("+"),
            "text": body,
        }
        if channel == ALPHANUMERIC_CHANNEL:
            if not from_value:
                raise ValueError(
                    "mamonty send on the 'char' channel needs a sender; "
                    "set one on the messaging row or use the 'digit' channel"
                )
            message["sender"] = from_value

        request: dict[str, Any] = {"apiKey": api_key, "sms": [message]}
        if status_url:
            request["webhookUrl"] = status_url

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._api_root()}/apiSms/create", json=request
            )
            response.raise_for_status()
            payload = response.json()

        sms_id = _accepted_id(payload)
        logger.info(
            f"mamonty sms to {to} via {channel}: accepted as {sms_id} "
            f"({self.segments(body)} segment(s))"
        )
        return sms_id

    def parse_callback(
        self, payload: Any, *, provider_ref: str | None = None
    ) -> CallbackVerdict:
        """Read one Mamonty status callback.

        The body is a list, because the provider batches. Our status URLs are
        per-message, so in practice the batch holds one entry — but "in
        practice" is not a guarantee, and a verdict written onto the wrong
        message is silent corruption, so the entry is matched by id.

        Args:
            payload: The decoded body — a list of status objects.
            provider_ref: The ``smsId`` we recorded at send time.

        Returns:
            The verdict; ``status`` is None when the batch says nothing about
            this message, or says something provisional.
        """
        entry = _entry_for(payload, provider_ref)
        if entry is None:
            return CallbackVerdict()

        status = DISPOSITIONS.get(str(entry.get("status") or "").lower())
        if status is None:
            return CallbackVerdict()

        # The callback spells this snake_case, where the REST API spells it
        # errorDescription; accept either so one parser reads both surfaces.
        error = entry.get("error_description") or entry.get("errorDescription")
        return CallbackVerdict(
            status=status, error=str(error)[:2000] if error else None
        )

    def _api_root(self) -> str:
        """The API root this account's requests go to, without a trailing slash."""
        return (self._config.control_url or MAMONTY_API_ROOT).rstrip("/")

    def _require_api_key(self) -> str:
        if not self._config.auth_token:
            raise ValueError("mamonty send needs an auth_token (the vendor's apiKey)")
        return self._config.auth_token


def _accepted_id(payload: Any) -> str:
    """The vendor's reference for the one message we sent.

    Mamonty answers ``{"status": "success", "data": [{"id": …, …}]}`` for a
    batch; we always send a batch of one.

    A refusal is not reported by the envelope. Asking for a channel the
    account does not have comes back HTTP 200, ``"status": "success"``, and
    the rejection sitting *inside* the entry — ``"status": "error"``, an
    ``errorDescription``, and no id at all. So the entry is what decides, and
    the vendor's own words are what the operator needs: "Access denied to
    create [digit] SMS" names the thing to fix, a generic parse failure does
    not.

    Args:
        payload: The decoded response body.

    Returns:
        The message's ``smsId`` as a string.

    Raises:
        ValueError: If the response is not one accepted message.
    """
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError(f"mamonty refused the message: {_reason(payload)}")

    entries = payload.get("data")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"mamonty accepted nothing: {str(payload)[:500]}")

    # A malformed entry carries neither a refusal nor an id, so it falls
    # through to the "no message id" refusal below with the body attached.
    entry = entries[0] if isinstance(entries[0], dict) else {}

    if (
        entry.get("status") == "error"
        or entry.get("errorDescription")
        or entry.get("errorCode")
    ):
        raise ValueError(f"mamonty refused the message: {_reason(entry)}")

    sms_id = entry.get("id")
    if sms_id is None:
        raise ValueError(f"mamonty returned no message id: {str(payload)[:500]}")
    return str(sms_id)


def _entry_for(payload: Any, provider_ref: str | None) -> Mapping[str, Any] | None:
    """The status object in `payload` that concerns our message, if any.

    A batch addressed to a per-message URL should hold exactly that message,
    and a lone entry in one is taken at its word — that is the only shape seen
    on the wire, and refusing it would throw away every verdict if the vendor
    ever omitted the id. More than one entry means the vendor grouped messages
    we cannot tell apart by URL, so the id has to decide.

    Args:
        payload: The decoded callback body.
        provider_ref: The ``smsId`` we recorded for this message.

    Returns:
        The matching entry, or None when the batch says nothing about us.
    """
    entries = payload if isinstance(payload, list) else [payload]
    entries = [entry for entry in entries if isinstance(entry, Mapping)]
    if not entries:
        return None

    if provider_ref:
        for entry in entries:
            if str(entry.get("id")) == provider_ref:
                return entry
        # Named someone else's messages only — not ours to write.
        if any(entry.get("id") is not None for entry in entries):
            logger.warning(
                f"mamonty callback for {provider_ref} carried no entry for it: "
                f"{[entry.get('id') for entry in entries]}"
            )
            return None

    if len(entries) > 1:
        logger.warning("mamonty callback batched several entries and named none")
        return None
    return entries[0]


def _reason(source: Any) -> str:
    """A refusal in the vendor's own words, or the raw body when it gave none.

    Only ``errorDescription`` is trusted as prose: an entry's ``message`` is
    the SMS text, and reporting the body of the message as the reason it was
    refused would send an operator looking in the wrong place.

    Args:
        source: The response envelope, or the rejected entry inside it.

    Returns:
        A single line, capped to what fits an error column.
    """
    if isinstance(source, dict):
        description = source.get("errorDescription")
        if description:
            code = source.get("errorCode")
            said = f"{description} [{code}]" if code else str(description)
            return said[:500]
    return str(source)[:500]


MessagingAdapters[MessagingAdapterEnum.mamonty] = MamontyMessagingAdapter
