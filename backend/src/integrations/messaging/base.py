"""Messaging adapters and the registry services resolve them through.

A messaging adapter owns one direction of one thing: handing a body of text to
a provider for delivery to a handset. It is the only place a vendor's SMS API
is spelled out — callers pass a destination and a body and receive back the
provider's reference for the message.

The pattern is the one every other kind in this package follows: a plain
pydantic config built from an organization's row (nothing here reads the
environment), behavioural divergences declared as :class:`MessagingCapabilities`
data and overridable per row, and a registry keyed off
:class:`~src.common.enums.engine.MessagingAdapterEnum`. Adding a vendor is an
enum value, an adapter module, and a DB row — never a branch in a service.

Scope: **outbound only**. Nothing here receives messages. Inbound SMS is a
webhook surface with its own storage and routing questions, and pretending the
contract covers it would be a lie an implementer discovers late.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from src.application.engine.capabilities import Capabilities
from src.common.enums.engine import MessageStatusEnum, MessagingAdapterEnum

# Re-exported: the schema lives in src/schemas (platform convention), the
# contract that consumes it lives here — same arrangement as telephony.
from src.schemas.messaging import MessagingConfig


@dataclass(frozen=True, slots=True)
class CallbackVerdict:
    """What one delivery callback says about one message.

    Deliberately the vendor's verdict translated, not the vendor's payload:
    the hooks service writes this and never sees a provider's vocabulary,
    which is what keeps a second vendor from becoming a second branch there.
    """

    #: Where the message has got to, or None when the callback carried nothing
    #: worth writing — a provisional status, or a batch with no entry for us.
    status: MessageStatusEnum | None = None
    #: Why it failed, in the provider's words. None when it did not.
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MessagingCapabilities(Capabilities):
    """How a messaging backend behaves, as data.

    Declared per adapter, overridable per organization's messaging row through
    :attr:`MessagingConfig.capabilities` — the same mechanism that lets an
    operator correct a deployment that disagrees with its documentation.
    """

    #: Characters one billable segment holds in the GSM-7 alphabet. Only used
    #: to *report* segment count back to the caller; nothing truncates.
    segment_chars: int = 160
    #: Characters per segment once any non-GSM-7 character forces UCS-2 —
    #: which, for Russian or emoji, is every message.
    unicode_segment_chars: int = 70
    #: Whether the provider can call back with delivery dispositions.
    supports_delivery_status: bool = False
    #: Whether the provider accepts an alphanumeric sender id in place of a
    #: number. Country-dependent in practice; this is the API-level answer.
    supports_alphanumeric_sender: bool = False
    #: Whether the provider owns a sender pool we address by id instead of
    #: naming a ``From`` (Twilio's Messaging Service).
    supports_sender_pool: bool = False


class BaseMessagingAdapter(ABC):
    """Contract every messaging backend in this package satisfies."""

    #: What this client assumes about a protocol it cannot negotiate. Logged
    #: by whoever selected the adapter, so swapping vendors swaps the caveats.
    protocol_assumptions: tuple[str, ...] = ()

    #: Defaults, overridable per organization from the messaging row.
    capabilities: MessagingCapabilities = MessagingCapabilities()

    @classmethod
    @abstractmethod
    def from_config(cls, config: MessagingConfig) -> Self:
        """Build an adapter from an organization's messaging row.

        Args:
            config: The organization's messaging binding.

        Returns:
            A ready adapter. It must not perform I/O until asked to.
        """

    @abstractmethod
    async def send(
        self,
        *,
        to: str,
        body: str,
        sender: str | None = None,
        status_url: str | None = None,
    ) -> str:
        """Hand one message to the provider for delivery.

        Args:
            to: Destination number, E.164.
            body: The message text, already final — adapters do not template,
                truncate, or split.
            sender: Overrides the config's default sender.
            status_url: Where the provider should report delivery. Ignored by
                adapters whose :attr:`MessagingCapabilities.supports_delivery_status`
                is False.

        Returns:
            The provider's reference for the message — what reconciles our
            record against the vendor's logs.

        Raises:
            ValueError: If credentials or a sender are missing.
        """

    def verify_callback(
        self,
        *,
        url: str | None,
        headers: Mapping[str, str],
        form: dict[str, str] | None,
    ) -> bool:
        """Whether a delivery callback really came from this provider.

        The default answers True: most providers sign nothing, and for those
        the only lock is the HMAC the status URL already carries, which the
        hooks service checks before this is ever called.

        An adapter whose provider *does* sign must fail closed — including
        when `url` is None, which means no public base is configured and the
        signed string cannot be rebuilt. A check that cannot run is not a
        check that passed.

        Args:
            url: The status URL as the provider was given it, or None when it
                cannot be reconstructed.
            headers: The request's headers.
            form: The POST form, when the body was form-encoded.

        Returns:
            True to let the verdict be believed.
        """
        return True

    def parse_callback(
        self, payload: Any, *, provider_ref: str | None = None
    ) -> CallbackVerdict:
        """Translate one delivery callback into our own vocabulary.

        The default records nothing, which is right for an adapter whose
        :attr:`MessagingCapabilities.supports_delivery_status` is False: no
        status URL was ever handed out, so nothing should arrive.

        Args:
            payload: The decoded body — a mapping, or a list where the
                provider batches several messages into one call.
            provider_ref: Our reference for the message this callback's URL
                addressed. An adapter whose provider batches uses it to pick
                the right entry; one whose provider names the message uses it
                to refuse a verdict meant for a different one.

        Returns:
            The verdict. ``status`` is None when there is nothing to write.
        """
        return CallbackVerdict()

    def segments(self, body: str) -> int:
        """How many billable segments `body` will cost.

        Computed from the adapter's declared capabilities rather than a
        vendor call, so an operator sees the cost before sending and a test
        sees it without a network. The GSM-7 extension table (``{}[]|^~\\€``,
        each two characters on the wire) is not modelled — a message built
        from those alone would be undercounted by up to a factor of two.

        Args:
            body: The message text.

        Returns:
            Segment count; 1 for an empty body, since a send still happens.
        """
        unicode_needed = any(ord(character) > 0x7F for character in body)
        per_segment = (
            self.capabilities.unicode_segment_chars
            if unicode_needed
            else self.capabilities.segment_chars
        )
        if len(body) <= per_segment:
            return 1
        # Concatenated messages spend 6 septets (or 3 UCS-2 characters) per
        # segment on the UDH that reassembles them.
        header = 3 if unicode_needed else 7
        usable = per_segment - header
        return -(-len(body) // usable)


#: Registry. Populated by each adapter module at import time.
MessagingAdapters: dict[MessagingAdapterEnum, type[BaseMessagingAdapter]] = {}


def build_messaging(config: MessagingConfig) -> BaseMessagingAdapter:
    """Resolve and build the messaging adapter named by `config`.

    Args:
        config: The organization's messaging row.

    Returns:
        An adapter, with the organization's capability overrides applied.

    Raises:
        KeyError: If no adapter is registered under that name.
    """
    adapter = MessagingAdapters.get(config.adapter)
    if adapter is None:
        raise KeyError(
            f"no messaging adapter registered as {config.adapter!r}. "
            f"Registered: {sorted(MessagingAdapters)}"
        )
    service = adapter.from_config(config)
    service.capabilities = adapter.capabilities.merged(config.capabilities)
    return service
