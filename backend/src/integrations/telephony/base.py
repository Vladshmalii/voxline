"""Telephony adapters and the registry the worker resolves them through.

A telephony adapter owns one call **leg**: how the provider's webhook is
answered, how its media WebSocket is turned into the Pipecat transport the
engine runs on, and how a leg is originated or torn down through the
provider's control API. It is the only place a provider's wire protocol is
spelled out — the engine receives a built ``BaseTransport`` and, per
``session.py``, never learns which vendor produced it.

The pattern is the same as STT/TTS/TTT: a plain pydantic config the worker can
build from an organization's rows (or a test fixture — nothing here reads the
environment), behavioural divergences declared as :class:`TelephonyCapabilities`
data and overridable per row, and a registry keyed off
:class:`~src.common.enums.engine.TelephonyAdapterEnum`. Adding a carrier is an
enum value, an adapter module, and a DB row — never a branch in the worker.

One shape difference from the model adapters: a transport needs a *live*
connection that only exists once the provider dials in, so the factory builds
the adapter from config alone, and the adapter builds the transport later,
when the worker hands it the accepted WebSocket (:meth:`answer_media`).

The expected call flows, in adapter-neutral terms:

Inbound::

    provider webhook → controller answers with adapter.answer_instructions(url)
    provider opens media WS → worker: adapter.answer_media(ws) → transport
    → CallSession(transport=...)

Outbound::

    worker: adapter.dial(to=..., media_url=...) → provider opens media WS
    → answer_media(ws) → transport → CallSession(...)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self

from fastapi import WebSocket
from pipecat.transports.base_transport import BaseTransport

from src.application.engine.capabilities import Capabilities
from src.common.enums.engine import TelephonyAdapterEnum

# Re-exported: the schema lives in src/schemas (platform convention), the
# contract that consumes it lives here. Existing import sites keep working.
from src.schemas.telephony import TelephonyConfig

#: How long :meth:`BaseTelephonyAdapter.answer_media` waits for the provider's
#: opening control message before giving up. A leg whose handshake never
#: arrives must fail here, loudly, not as a silent call.
DEFAULT_HANDSHAKE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class TelephonyCapabilities(Capabilities):
    """How a telephony leg behaves on the wire.

    Declared per adapter, overridable per organization's telephony row through
    :attr:`TelephonyConfig.capabilities` — the same mechanism that lets an
    operator correct an STT deployment that disagrees with its documentation.
    """

    #: Rate of the media the provider sends and expects. Telephony is 8 kHz
    #: almost everywhere; the serializer resamples, nothing else should.
    sample_rate: int = 8000
    #: Wire codec: ``"ulaw"`` or ``"pcm16"``.
    encoding: str = "ulaw"
    #: Whether the media WebSocket opens with a control message (a Twilio
    #: ``start`` event, a bridge ``start`` envelope) that must be consumed
    #: before audio flows. False means audio from the first frame.
    expects_start_event: bool = True
    #: Can originate an outbound leg through a control API.
    supports_dial: bool = False
    #: Can end the leg through a control API (vs just closing the socket).
    supports_api_hangup: bool = False
    #: Delivers DTMF key presses as events.
    supports_dtmf: bool = False


class BaseTelephonyAdapter(ABC):
    """Contract every telephony leg in this package satisfies."""

    #: What this client assumes about a protocol it cannot negotiate. Logged
    #: once per call by whoever selected the adapter, so swapping the carrier
    #: swaps the caveats with it.
    protocol_assumptions: tuple[str, ...] = ()

    #: Defaults, overridable per organization from the telephony row.
    capabilities: TelephonyCapabilities = TelephonyCapabilities()

    @classmethod
    @abstractmethod
    def from_config(cls, config: TelephonyConfig, *, call_id: str) -> Self:
        """Build an adapter for one call.

        Per call, never shared: credentials differ per organization and the
        media handshake below carries per-leg state.

        Args:
            config: The organization's telephony row.
            call_id: Correlation id, passed to providers that accept one.

        Returns:
            A ready adapter. It must not perform I/O until asked to.
        """

    @abstractmethod
    async def answer_media(self, websocket: WebSocket) -> BaseTransport:
        """Turn an accepted media WebSocket into the transport a session runs on.

        Performs the provider's opening handshake (consuming the start event
        when :attr:`TelephonyCapabilities.expects_start_event` says one comes)
        and wires the provider's serializer. The WebSocket must already be
        accepted by the controller — adapters do not own HTTP routing.

        Args:
            websocket: The accepted media connection.

        Returns:
            A transport ready for ``CallSession``.

        Raises:
            TimeoutError: If the provider's handshake never arrives.
            ValueError: If the handshake is malformed.
        """

    def answer_instructions(self, media_url: str) -> str | None:
        """The webhook answer that routes this call's media to `media_url`.

        Provider-specific payload (TwiML for Twilio), returned as a string for
        the controller to serve with the right content type. None when the
        provider is driven purely by its control API and answers no webhook.

        Args:
            media_url: Public WebSocket URL the provider should stream to.

        Returns:
            The answer body, or None.
        """
        return None

    async def dial(
        self,
        *,
        to: str,
        media_url: str,
        caller_id: str | None = None,
        status_url: str | None = None,
    ) -> str:
        """Originate an outbound leg that streams its media to `media_url`.

        Args:
            to: Destination number, E.164.
            media_url: Public WebSocket URL for the leg's media.
            caller_id: Overrides the config's default caller id.
            status_url: Where the provider should report the leg's fate
                (busy, no answer, failed…). Optional — a provider that cannot
                deliver dispositions leaves the sweep timers to decide.

        Returns:
            The provider's reference for the leg, for :meth:`hangup` and logs.

        Raises:
            NotImplementedError: If the adapter cannot originate calls.
        """
        raise NotImplementedError(f"{type(self).__name__} cannot originate calls")

    async def hangup(self, call_ref: str) -> None:
        """End a leg through the provider's control API.

        Args:
            call_ref: The reference :meth:`dial` returned, or the provider's
                call id from the media handshake.

        Raises:
            NotImplementedError: If the adapter has no control API.
        """
        raise NotImplementedError(f"{type(self).__name__} cannot hang up via API")


#: Registry. Populated by each adapter module at import time.
TelephonyAdapters: dict[TelephonyAdapterEnum, type[BaseTelephonyAdapter]] = {}


def build_telephony(config: TelephonyConfig, *, call_id: str) -> BaseTelephonyAdapter:
    """Resolve and build the telephony adapter named by `config`.

    Args:
        config: The organization's telephony row.
        call_id: Correlation id for the call.

    Returns:
        An adapter, with the organization's capability overrides applied.

    Raises:
        KeyError: If no adapter is registered under that name.
    """
    adapter = TelephonyAdapters.get(config.adapter)
    if adapter is None:
        raise KeyError(
            f"no telephony adapter registered as {config.adapter!r}. "
            f"Registered: {sorted(TelephonyAdapters)}"
        )
    service = adapter.from_config(config, call_id=call_id)
    service.capabilities = adapter.capabilities.merged(config.capabilities)
    return service
