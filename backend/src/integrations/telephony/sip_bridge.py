"""A self-hosted SIP service as a call leg, behind a bridge contract we define.

The SIP side has not been chosen yet, and this module is written so it does
not have to be: instead of speaking some vendor's dialect, it publishes the
contract the platform expects from *whatever* bridges SIP/RTP to a WebSocket.
When the service is picked, either it conforms (most media gateways can be
told what to send), a thin shim maps its protocol onto this one, or the
divergences are absorbed here — first through capability and option overrides
in the organization's telephony row, and only as a last resort as code.

The media contract, per leg:

* the bridge opens one WebSocket to our media URL;
* **binary frames are raw audio** — µ-law or PCM16 at
  ``TelephonyCapabilities.encoding``/``sample_rate`` (8 kHz µ-law default,
  because that is what a SIP leg almost always carries);
* **text frames are JSON control envelopes**::

      {"event": "start", "call_id": "...", ...}   before the first audio
      {"event": "dtmf",  "digit": "5"}
      {"event": "stop",  "reason": "..."}         the leg died on the SIP side

* in the other direction we send binary audio in the same encoding, plus
  ``{"event": "clear"}`` on barge-in (drop buffered playback) and
  ``{"event": "stop"}`` when the call ends on our side.

The control contract (optional — only if the bridge exposes a REST API,
configured via ``control_url``):

* ``POST {control_url}/calls`` with ``{"to", "from", "media_url", "call_id"}``
  originates a leg and returns ``{"call_id": ...}``;
* ``POST {control_url}/calls/{ref}/hangup`` ends one.

Everything negotiable is data: a bridge that ships PCM16 at 16 kHz is two
capability overrides in a DB row, one that starts streaming without a start
event is ``expects_start_event: false`` — no code release either way.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Self

import httpx
from fastapi import WebSocket
from loguru import logger
from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

from src.application.engine.audio import ASR_SAMPLE_RATE
from src.common.enums.engine import TelephonyAdapterEnum
from src.integrations.telephony.base import (
    DEFAULT_HANDSHAKE_TIMEOUT_SECONDS,
    BaseTelephonyAdapter,
    TelephonyAdapters,
    TelephonyCapabilities,
    TelephonyConfig,
)
from src.integrations.telephony.websocket import PacedFastAPIWebsocketTransport

#: Remaining uncertainties — honest ones, since the far side does not exist yet.
PROTOCOL_ASSUMPTIONS: tuple[str, ...] = (
    "binary frames carry raw audio in the configured encoding, nothing framed",
    "the bridge tolerates our stop/clear envelopes even if it ignores them",
    "one WebSocket per leg; the bridge never multiplexes calls",
)


class SipBridgeFrameSerializer(FrameSerializer):
    """Pipecat frames to and from the bridge wire contract above.

    µ-law or PCM16 chosen by config, resampled between the bridge's rate and
    the pipeline's — the same one-place-only conversion rule the rest of the
    stack follows.
    """

    def __init__(
        self,
        *,
        encoding: str = "ulaw",
        bridge_sample_rate: int = 8000,
        send_stop_on_end: bool = True,
        params: FrameSerializer.InputParams | None = None,
    ) -> None:
        """Initialise the serializer.

        Args:
            encoding: ``"ulaw"`` or ``"pcm16"``.
            bridge_sample_rate: Rate of the audio on the wire.
            send_stop_on_end: Emit the ``stop`` envelope on EndFrame/CancelFrame
                so the bridge tears the SIP leg down promptly.
            params: Base serializer parameters.
        """
        if encoding not in ("ulaw", "pcm16"):
            raise ValueError(f"unsupported bridge encoding {encoding!r}")
        super().__init__(params or FrameSerializer.InputParams())
        self._encoding = encoding
        self._bridge_rate = bridge_sample_rate
        self._send_stop_on_end = send_stop_on_end
        self._sample_rate = 0
        self._input_resampler = create_stream_resampler(
            clear_after_secs=self._params.resampler_clear_after_secs
        )
        self._output_resampler = create_stream_resampler(
            clear_after_secs=self._params.resampler_clear_after_secs
        )
        self._stopped = False

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Adopt the pipeline's input rate."""
        self._sample_rate = setup.audio_in_sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        """Pipecat frame → wire. Audio as binary, control as JSON text."""
        if isinstance(frame, (EndFrame, CancelFrame)):
            if not self._send_stop_on_end or self._stopped:
                return None
            self._stopped = True
            return json.dumps({"event": "stop"})
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"event": "clear"})
        if isinstance(frame, AudioRawFrame):
            if self._encoding == "ulaw":
                data = await pcm_to_ulaw(
                    frame.audio,
                    frame.sample_rate,
                    self._bridge_rate,
                    self._output_resampler,
                )
            else:
                data = await self._output_resampler.resample(
                    frame.audio, frame.sample_rate, self._bridge_rate
                )
            return data if data else None
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """Wire → Pipecat frame. Binary is audio; text is a control envelope."""
        if isinstance(data, bytes):
            if self._encoding == "ulaw":
                pcm = await ulaw_to_pcm(
                    data, self._bridge_rate, self._sample_rate, self._input_resampler
                )
            else:
                pcm = await self._input_resampler.resample(
                    data, self._bridge_rate, self._sample_rate
                )
            if not pcm:
                return None
            return InputAudioRawFrame(
                audio=pcm, sample_rate=self._sample_rate, num_channels=1
            )

        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            logger.warning(f"sip bridge: non-JSON text frame discarded: {data[:80]!r}")
            return None

        event = message.get("event")
        if event == "dtmf":
            digit = str(message.get("digit", ""))
            try:
                return InputDTMFFrame(KeypadEntry(digit))
            except ValueError:
                logger.warning(f"sip bridge: unrecognised DTMF digit {digit!r}")
                return None
        if event == "stop":
            # The SIP side ended; the socket close that follows tears the
            # pipeline down. Logged so "who hung up" is answerable later.
            logger.info(
                f"sip bridge: leg stopped ({message.get('reason', 'no reason')})"
            )
            return None
        logger.debug(f"sip bridge: ignoring event {event!r}")
        return None


class SipBridgeTelephonyAdapter(BaseTelephonyAdapter):
    """One leg carried by an external SIP↔WebSocket bridge."""

    protocol_assumptions = PROTOCOL_ASSUMPTIONS

    capabilities: TelephonyCapabilities = TelephonyCapabilities(
        sample_rate=8000,
        encoding="ulaw",
        expects_start_event=True,
        supports_dial=True,
        supports_api_hangup=True,
        supports_dtmf=True,
    )

    @classmethod
    def from_config(cls, config: TelephonyConfig, *, call_id: str) -> Self:
        """Build a leg from an organization's telephony row.

        Recognised ``options``: ``session_timeout`` (seconds of transport
        inactivity), ``handshake_timeout`` (seconds to wait for the start
        envelope), ``audio_in_sample_rate`` (pipeline input rate; defaults to
        the ASR rate), ``send_stop_on_end`` (emit the stop envelope; default
        True).
        """
        return cls(config, call_id=call_id)

    def __init__(self, config: TelephonyConfig, *, call_id: str) -> None:
        """Initialise the adapter. No I/O happens here."""
        self._config = config
        self._call_id = call_id
        options = config.options
        self._session_timeout: int | None = options.get("session_timeout")
        self._handshake_timeout: float = float(
            options.get("handshake_timeout", DEFAULT_HANDSHAKE_TIMEOUT_SECONDS)
        )
        self._audio_in_sample_rate: int = int(
            options.get("audio_in_sample_rate", ASR_SAMPLE_RATE)
        )
        self._send_stop_on_end: bool = bool(options.get("send_stop_on_end", True))

    # -- media ----------------------------------------------------------------

    async def answer_media(self, websocket: WebSocket) -> BaseTransport:
        """Consume the start envelope (when expected) and build the transport.

        Args:
            websocket: The accepted media connection from the bridge.

        Returns:
            A transport speaking the bridge contract through the serializer.

        Raises:
            TimeoutError: If the start envelope never arrives.
        """
        if self.capabilities.expects_start_event:
            start = await self._read_start_event(websocket)
            logger.info(
                f"call {self._call_id}: sip bridge media started "
                f"(bridge call={start.get('call_id')})"
            )

        serializer = SipBridgeFrameSerializer(
            encoding=self.capabilities.encoding,
            bridge_sample_rate=self.capabilities.sample_rate,
            send_stop_on_end=self._send_stop_on_end,
        )
        return PacedFastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=self._audio_in_sample_rate,
                add_wav_header=False,
                serializer=serializer,
                session_timeout=self._session_timeout,
            ),
        )

    async def _read_start_event(self, websocket: WebSocket) -> dict[str, Any]:
        """Wait for the ``start`` envelope; audio before it is a contract breach."""
        async with asyncio.timeout(self._handshake_timeout):
            while True:
                raw = await websocket.receive_text()
                message = json.loads(raw)
                if message.get("event") == "start":
                    return message
                logger.debug(
                    f"call {self._call_id}: ignoring bridge event "
                    f"{message.get('event')!r} before start"
                )

    # -- control --------------------------------------------------------------

    async def dial(
        self,
        *,
        to: str,
        media_url: str,
        caller_id: str | None = None,
        status_url: str | None = None,
    ) -> str:
        """Originate a leg through the bridge's control API.

        Args:
            to: Destination number, E.164.
            media_url: Public WebSocket URL for the leg's media.
            caller_id: Overrides the config's default caller id.
            status_url: Where the bridge should POST the leg's disposition —
                part of the control contract in the module docstring.

        Returns:
            The bridge's reference for the leg.

        Raises:
            ValueError: If no ``control_url`` is configured.
            httpx.HTTPStatusError: If the bridge rejects the request.
        """
        control_url = self._require_control_url("dial")
        async with httpx.AsyncClient(headers=self._auth_headers()) as client:
            response = await client.post(
                f"{control_url}/calls",
                json={
                    "to": to,
                    "from": caller_id or self._config.caller_id,
                    "media_url": media_url,
                    "status_url": status_url,
                    "call_id": self._call_id,
                },
            )
            response.raise_for_status()
            ref = str(response.json()["call_id"])
        logger.info(f"call {self._call_id}: sip bridge dialled {to} (ref={ref})")
        return ref

    async def hangup(self, call_ref: str) -> None:
        """End a leg through the bridge's control API.

        Args:
            call_ref: The reference :meth:`dial` returned.
        """
        control_url = self._require_control_url("hangup")
        async with httpx.AsyncClient(headers=self._auth_headers()) as client:
            response = await client.post(f"{control_url}/calls/{call_ref}/hangup")
            # 404: the leg is already gone, which is the outcome we wanted.
            if response.status_code != 404:
                response.raise_for_status()

    def _require_control_url(self, action: str) -> str:
        if not self._config.control_url:
            raise ValueError(f"sip bridge {action} needs control_url configured")
        return self._config.control_url.rstrip("/")

    def _auth_headers(self) -> dict[str, str]:
        if not self._config.auth_token:
            return {}
        return {"Authorization": f"Bearer {self._config.auth_token}"}


TelephonyAdapters[TelephonyAdapterEnum.sip_bridge] = SipBridgeTelephonyAdapter
