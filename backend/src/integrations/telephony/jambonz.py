"""A self-hosted jambonz stack as a call leg, speaking its ``listen`` verb.

The media contract, per leg — confirmed live against this platform's own
jambonz deployment (0.9.8), not against jambonz's published docs, since the
two disagree in ways that only show up on the wire:

* the ``listen`` verb runs over FreeSWITCH's ``mod_audio_fork``, which opens
  one WebSocket to our media URL and streams **binary audio from its very
  first frame** — there is no preceding text metadata frame to read, unlike
  every other adapter in this package (and unlike what jambonz's own docs and
  this platform's echo-server test harness both implied). Reading one anyway
  throws (``receive_text()`` on a binary frame is a ``KeyError``) and drops
  the caller's first words on the floor;
* **binary frames are raw L16 PCM, little-endian, mono**, at the rate and mix
  our own ``/answer`` webhook told jambonz to use in the ``listen`` verb
  (``TelephonyCapabilities.sample_rate``/``mixType: "mono"`` in
  ``controller_hooks/api/v1/media.py``) — nothing on the wire announces it,
  so this adapter must already know it. There is no µ-law option to negotiate;
* DTMF arrives as a text frame ``{"event": "dtmf", "dtmf": "<digit>", ...}``;
* we control the leg over the same socket: ``{"type": "killAudio"}`` drops
  buffered playback on barge-in, ``{"type": "disconnect"}`` ends the call
  from our side.

The control contract (jambonz's REST Calls API) has been confirmed live
against this deployment's account: a request needs ``call_hook`` *and*
either ``application_sid`` or a full speech vendor/language/voice set, even
when the leg opens straight into ``listen`` and never touches jambonz's own
TTS/STT. Unlike Twilio, jambonz has no inline-instructions parameter:
originating or answering a call always means jambonz fetching a
``call_hook`` webhook that returns a verb array, so :func:`_answer_hook_url`
derives that webhook's URL from the media URL, and
``controller_hooks/api/v1/media.py`` serves it.
"""

from __future__ import annotations

import json
from typing import Any, Self
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import WebSocket
from loguru import logger
from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.audio.utils import create_stream_resampler
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
    BaseTelephonyAdapter,
    TelephonyAdapters,
    TelephonyCapabilities,
    TelephonyConfig,
)
from src.integrations.telephony.websocket import PacedFastAPIWebsocketTransport
from src.utils.url import http_url

#: Remaining uncertainties — honest ones, since half this contract comes from
#: one test harness, not a spec.
PROTOCOL_ASSUMPTIONS: tuple[str, ...] = (
    (
        "confirmed live: the leg opens with binary audio, no metadata "
        "handshake frame -- expects_start_event is False for this reason, "
        "not merely by default"
    ),
    "audio is always raw L16 PCM, little-endian, mono; there is no ulaw mode",
    "dtmf is {'event': 'dtmf', 'dtmf': '<digit>'}, not {'event': 'dtmf', 'digit': ...}",
    "we control the leg with {'type': 'killAudio'} and {'type': 'disconnect'}",
    (
        "Calls API POST body needs call_hook plus a full speech vendor/"
        "language/voice set (confirmed live: jambonz 400s without it, even "
        "though a call_hook leg never uses jambonz's own TTS/STT) -- the "
        "values sent are inert placeholders, not a real vendor choice"
    ),
)


class JambonzFrameSerializer(FrameSerializer):
    """Pipecat frames to and from jambonz's ``listen`` wire contract.

    Always raw PCM16, little-endian, mono — jambonz offers no other encoding
    on this leg, so unlike :class:`SipBridgeFrameSerializer` there is no codec
    branch, only the resample every telephony serializer needs.
    """

    def __init__(
        self,
        *,
        bridge_sample_rate: int,
        send_disconnect_on_end: bool = True,
        params: FrameSerializer.InputParams | None = None,
    ) -> None:
        """Initialise the serializer.

        Args:
            bridge_sample_rate: Rate of the audio on the wire, taken from the
                call's opening metadata frame.
            send_disconnect_on_end: Emit the ``disconnect`` control frame on
                EndFrame/CancelFrame so jambonz tears the leg down promptly.
            params: Base serializer parameters.
        """
        super().__init__(params or FrameSerializer.InputParams())
        self._bridge_rate = bridge_sample_rate
        self._send_disconnect_on_end = send_disconnect_on_end
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
            if not self._send_disconnect_on_end or self._stopped:
                return None
            self._stopped = True
            return json.dumps({"type": "disconnect"})
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "killAudio"})
        if isinstance(frame, AudioRawFrame):
            data = await self._output_resampler.resample(
                frame.audio, frame.sample_rate, self._bridge_rate
            )
            return data if data else None
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """Wire → Pipecat frame. Binary is audio; text is a control envelope."""
        if isinstance(data, bytes):
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
            logger.warning(f"jambonz: non-JSON text frame discarded: {data[:80]!r}")
            return None

        if message.get("event") == "dtmf":
            digit = str(message.get("dtmf", ""))
            try:
                return InputDTMFFrame(KeypadEntry(digit))
            except ValueError:
                logger.warning(f"jambonz: unrecognised DTMF digit {digit!r}")
                return None
        logger.debug(f"jambonz: ignoring control frame {message!r}")
        return None


class JambonzTelephonyAdapter(BaseTelephonyAdapter):
    """One jambonz ``listen`` leg, dialled and answered through its REST Calls API."""

    protocol_assumptions = PROTOCOL_ASSUMPTIONS

    capabilities: TelephonyCapabilities = TelephonyCapabilities(
        sample_rate=8000,
        encoding="pcm16",
        expects_start_event=False,
        supports_dial=True,
        supports_api_hangup=True,
        supports_dtmf=True,
    )

    @classmethod
    def from_config(cls, config: TelephonyConfig, *, call_id: str) -> Self:
        """Build a leg from an organization's telephony row.

        Recognised ``options``: ``session_timeout`` (seconds of transport
        inactivity), ``audio_in_sample_rate`` (pipeline input rate; defaults
        to the ASR rate), ``send_disconnect_on_end`` (send the disconnect
        control frame on EndFrame; default True).
        """
        return cls(config, call_id=call_id)

    def __init__(self, config: TelephonyConfig, *, call_id: str) -> None:
        """Initialise the adapter. No I/O happens here."""
        self._config = config
        self._call_id = call_id
        options = config.options
        self._session_timeout: int | None = options.get("session_timeout")
        self._audio_in_sample_rate: int = int(
            options.get("audio_in_sample_rate", ASR_SAMPLE_RATE)
        )
        self._send_disconnect_on_end: bool = bool(
            options.get("send_disconnect_on_end", True)
        )

    # -- media ----------------------------------------------------------------

    async def answer_media(self, websocket: WebSocket) -> BaseTransport:
        """Build the transport. jambonz's leg opens with audio, no handshake.

        Confirmed live (not merely assumed, unlike the rest of this module's
        history): the underlying FreeSWITCH ``mod_audio_fork`` leg that
        ``listen`` opens sends binary audio from its very first frame, with
        no preceding text metadata frame to read — reading one here throws
        (``receive_text()`` on a binary frame is a ``KeyError``) and drops
        the caller's first words on the floor. The rate/mix this leg uses is
        already ours to know: it is exactly what our own ``/answer`` webhook
        told jambonz to use in the ``listen`` verb (see
        ``controller_hooks/api/v1/media.py``), so :attr:`capabilities` names
        it without needing to read anything off the wire.

        Args:
            websocket: The accepted media connection from jambonz.

        Returns:
            A transport speaking jambonz's dialect through the serializer.
        """
        serializer = JambonzFrameSerializer(
            bridge_sample_rate=self.capabilities.sample_rate,
            send_disconnect_on_end=self._send_disconnect_on_end,
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

    # -- control --------------------------------------------------------------

    async def dial(
        self,
        *,
        to: str,
        media_url: str,
        caller_id: str | None = None,
        status_url: str | None = None,
    ) -> str:
        """Originate an outbound call through jambonz's REST Calls API.

        jambonz answers by fetching a ``call_hook`` webhook — there is no
        inline equivalent of Twilio's ``Twiml`` parameter — so this points
        jambonz at this leg's own answer endpoint, derived from `media_url`
        (see :func:`_answer_hook_url`), which the controller serves and which
        in turn returns the ``listen`` verb pointed at `media_url` itself.

        Args:
            to: Destination number, E.164.
            media_url: Public WebSocket URL for the leg's media.
            caller_id: Overrides the config's default caller id.
            status_url: Where jambonz should POST the leg's disposition.

        Returns:
            jambonz's call SID for the leg.

        Raises:
            ValueError: If credentials or a caller id are missing.
            httpx.HTTPStatusError: If jambonz rejects the request.
        """
        account_id, auth_token = self._require_credentials("dial")
        from_number = caller_id or self._config.caller_id
        if not from_number:
            raise ValueError("jambonz dial needs a caller_id (config or per-call)")

        body: dict[str, Any] = {
            "from": from_number,
            "to": {"type": "phone", "number": to},
            "call_hook": {"url": _answer_hook_url(media_url), "method": "POST"},
            # jambonz's Calls API rejects a request lacking either an
            # application_sid or a full speech vendor/language/voice set,
            # even though a call_hook that opens straight into `listen`
            # never touches jambonz's own TTS/STT. Inert values that satisfy
            # the schema, nothing more.
            "speech_synthesis_vendor": "google",
            "speech_synthesis_language": "en-US",
            "speech_synthesis_voice": "en-US-Standard-C",
            "speech_recognizer_vendor": "google",
            "speech_recognizer_language": "en-US",
        }
        if status_url:
            body["call_status_hook"] = {"url": status_url, "method": "POST"}

        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {auth_token}"}
        ) as client:
            response = await client.post(
                f"{self._api_root()}/v1/Accounts/{account_id}/Calls",
                json=body,
            )
            if response.status_code >= 400:
                logger.error(
                    f"call {self._call_id}: jambonz dial to {to} rejected "
                    f"({response.status_code}): {response.text}"
                )
            response.raise_for_status()
            call_sid = response.json()["sid"]
        logger.info(f"call {self._call_id}: jambonz dialled {to} (call={call_sid})")
        return call_sid

    async def hangup(self, call_ref: str) -> None:
        """End a call by updating its status through jambonz's REST API.

        Args:
            call_ref: The call SID :meth:`dial` returned.
        """
        account_id, auth_token = self._require_credentials("hangup")
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {auth_token}"}
        ) as client:
            response = await client.post(
                f"{self._api_root()}/v1/Accounts/{account_id}/Calls/{call_ref}",
                json={"call_status": "completed"},
            )
            # 404: the leg is already gone, which is the outcome we wanted.
            if response.status_code != 404:
                response.raise_for_status()

    def _api_root(self) -> str:
        if not self._config.control_url:
            raise ValueError(
                "jambonz needs control_url configured (its API server root)"
            )
        return self._config.control_url.rstrip("/")

    def _require_credentials(self, action: str) -> tuple[str, str]:
        if not (self._config.account_id and self._config.auth_token):
            raise ValueError(f"jambonz {action} needs account_id and auth_token")
        return self._config.account_id, self._config.auth_token


def _answer_hook_url(media_url: str) -> str:
    """The HTTP webhook jambonz fetches to learn this leg's verbs.

    Derived from `media_url` rather than minted separately: same call uuid,
    same token, the same "one function, one derivation" rule
    ``registry.call_urls`` already follows for the media/status pair — this
    is just the one extra URL jambonz needs that that helper does not produce.
    """
    parts = urlsplit(http_url(media_url))
    path = parts.path.rstrip("/") + "/answer"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


TelephonyAdapters[TelephonyAdapterEnum.jambonz] = JambonzTelephonyAdapter
