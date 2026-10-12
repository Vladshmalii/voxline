"""Streaming Qwen3-ASR-1.7B client for Pipecat.

Pipecat ships no Qwen3-ASR integration, so this module is the custom one. It
subclasses :class:`~pipecat.services.stt_service.WebsocketSTTService`, which
gives us reconnect-with-backoff, keepalive, and the STT frame lifecycle; what is
written here is the wire protocol, the VAD gate, and stable-prefix tracking.

========================  TRANSPORT CONTRACT  ========================

**Verified against a live vLLM deployment**, not assumed. vLLM serves Qwen3-ASR
on a ``/v1/realtime`` WebSocket. The event names echo OpenAI's Realtime API but
the schema diverges from it in three ways that matter, which is why Pipecat's
stock ``OpenAIRealtimeSTTService`` cannot drive it and this client exists:

1. ``model`` is a **top-level** field of ``session.update``, not nested under
   ``session.audio.input.transcription``. Nesting it yields
   ``"Missing required field: model"``.
2. Transcripts arrive as ``transcription.delta`` — not
   ``conversation.item.input_audio_transcription.delta``.
3. ``error`` carries a **string**, not an object. Code that does
   ``evt["error"].get("message")`` raises ``AttributeError`` instead of
   reporting the error.

Connection
----------
One WebSocket per call, dialed at ``SttConfig.websocket_url()`` — the provider
row's HTTP base with the scheme swapped and ``/v1/realtime`` appended, unless
the row pins a full ``wss://`` URL or overrides ``options["ws_path"]``. The
provider's API key, if set, is sent as ``Authorization: Bearer <key>``; the
server answers 401 without it.

Server → client, on connect::

    {"type": "session.created", "id": "sess-...", "created": 1786487048}

Client → server
---------------
1. **Configure** (after ``session.created``)::

       {"type": "session.update",
        "model": "Qwen/Qwen3-ASR-1.7B",
        "session": {"turn_detection": null, "input_audio_format": "pcm16"}}

   ``model`` must match a name from the server's ``/v1/models``, or you get
   ``"The model ... does not exist."``. ``turn_detection: null`` disables
   server-side endpointing — Silero and Smart Turn own turn boundaries here.

   The server acknowledges this **silently**: there is no ``session.updated``.

2. **Audio**: base64-encoded 16 kHz mono PCM16, ~200 ms per message::

       {"type": "input_audio_buffer.append", "audio": "<base64>"}

3. **Finalize**::

       {"type": "input_audio_buffer.commit"}

Server → client
---------------
Transcription arrives as a stream of deltas and **nothing else** — there is no
completion event::

    {"type": "transcription.delta", "delta": "Hello"}

Concatenated, the stream carries a preamble before the transcript::

    language English<asr_text>Hello. My name is Anna, ...\n

so the detected language is announced up front, ``<asr_text>`` separates it from
the transcript, and a trailing newline ends the utterance. Since no ``.done``
event exists, that newline is the finalization signal;
:data:`ASR_TEXT_MARKER` and :data:`_PREAMBLE_RE` do the parsing.

Errors::

    {"type": "error", "error": "Missing required field: model", "code": "invalid_event"}

Language
--------
The server auto-detects and reports the language in the preamble. Forcing it is
not exposed on this endpoint, so :attr:`Qwen3ASRService.detected_language` is
observed rather than commanded — if it disagrees with the call metadata, that is
worth logging and acting on upstream rather than silently overriding.

=====================================================================
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Final

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import WebsocketSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from websockets.protocol import State

from src.application.engine.audio import (
    ASR_SAMPLE_RATE,
    AudioPath,
    bytes_for_duration,
    duration_of,
)
from src.application.engine.capabilities import SttCapabilities
from src.application.engine.config import SttConfig
from src.common.enums.engine import SttAdapterEnum
from src.integrations.stt.base import BaseSttAdapter, SttAdapters, UtteranceBuffer

#: Remaining uncertainties in the contract above. bot.py logs these at startup.
PROTOCOL_ASSUMPTIONS: Final[tuple[str, ...]] = (
    "no completion event exists; a trailing newline ends the utterance",
    "the server never sends session.updated, so config is assumed applied",
    "language is auto-detected and reported, not forced from call metadata",
)

#: Separates the language preamble from the transcript in the delta stream.
ASR_TEXT_MARKER: Final[str] = "<asr_text>"

#: Matches the ``language <Name>`` preamble that precedes :data:`ASR_TEXT_MARKER`.
_PREAMBLE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*language\s+(?P<language>[\w_]+)\s*"
)

# How much audio to keep while the gate is shut. Silero reports speech a beat
# after it actually starts, so without a pre-roll the first phoneme of every turn
# is missing and short words ("no", "yes") get lost outright.
DEFAULT_PREROLL_MS: Final[int] = 320

#: Minimum audio the server needs buffered before ``commit`` yields anything.
#:
#: Measured, not guessed: with 2.1s of speech, commit returns an empty stream at
#: buffer lengths of 2s, 3s and 4s, and the correct transcript at 5s. Short
#: replies — "yes", "no", "that works" — are precisely what a caller says when
#: answering promptly, so without padding the agent goes deaf exactly when the
#: conversation is going well.
MIN_COMMIT_SECONDS: Final[float] = 5.0

#: Served model name, overridable per backend in config.yaml.
DEFAULT_ASR_MODEL: Final[str] = "Qwen/Qwen3-ASR-1.7B"

#: The preamble announces language *names* ("language Russian<asr_text>"),
#: while everything downstream — language rows, ``match_language``, the switch
#: policy — speaks lowercase codes. The mapping lives here because the shape of
#: the preamble is this backend's quirk, not the engine's concern; a name the
#: map does not know passes through lowercased, matches no configured language,
#: and is visible as itself in the logs rather than silently dropped.
_LANGUAGE_CODES: Final[dict[str, str]] = {
    "arabic": "ar",
    "bengali": "bn",
    "cantonese": "yue",
    "chinese": "zh",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "filipino": "fil",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hebrew": "he",
    "hindi": "hi",
    "hungarian": "hu",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "javanese": "jv",
    "korean": "ko",
    "malay": "ms",
    "mandarin": "zh",
    "norwegian": "no",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "romanian": "ro",
    "russian": "ru",
    "spanish": "es",
    "swedish": "sv",
    "tagalog": "fil",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "urdu": "ur",
    "vietnamese": "vi",
}


def language_code(reported: str) -> str:
    """Normalise a preamble language to the lowercase code the engine speaks.

    Args:
        reported: The name from the preamble ("Russian"), or already a code.

    Returns:
        A lowercase code ("ru"); unknown names pass through lowercased.
    """
    lowered = reported.strip().lower().replace("_", "-")
    return _LANGUAGE_CODES.get(lowered, lowered)


@dataclass
class PrefixUpdate:
    """One revision of the running hypothesis."""

    stable_prefix: str
    unstable_tail: str

    @property
    def text(self) -> str:
        """The full current hypothesis."""
        return self.stable_prefix + self.unstable_tail


class StablePrefixTracker:
    """Splits a revisable hypothesis into a settled prefix and a volatile tail.

    Streaming ASR output is not append-only: "i'd like to check my order" can
    become "I'd like to check my quota" two frames later. Anything downstream
    that acts on a partial — speculative retrieval, LLM prefill, an on-screen
    caption — must act only on the part that has stopped moving, or it spends its
    budget on text that gets retracted.

    When the server reports ``stable_prefix_len`` this trusts it. When it does
    not, stability is derived: the longest common prefix of consecutive
    hypotheses, cut back to a word boundary (a shared partial word is not a
    settled word), and never allowed to shrink within an utterance.
    """

    def __init__(self) -> None:
        """Start with an empty hypothesis."""
        self._previous = ""
        self._stable_len = 0

    @property
    def stable_prefix(self) -> str:
        """The part of the current hypothesis that will not be revised."""
        return self._previous[: self._stable_len]

    @property
    def unstable_tail(self) -> str:
        """The part still subject to revision."""
        return self._previous[self._stable_len :]

    def reset(self) -> None:
        """Clear state at an utterance boundary."""
        self._previous = ""
        self._stable_len = 0

    def update(
        self, hypothesis: str, *, server_stable_len: int | None = None
    ) -> PrefixUpdate:
        """Fold a new hypothesis in and return the resulting split.

        Args:
            hypothesis: The server's current full hypothesis for the utterance.
            server_stable_len: Characters the server guarantees are final, if it
                said. ``None`` means derive it.

        Returns:
            The stable/unstable split after this revision.
        """
        if server_stable_len is not None:
            stable_len = max(0, min(int(server_stable_len), len(hypothesis)))
        else:
            stable_len = self._derive_stable_len(hypothesis)

        # Monotonic within an utterance: once settled, always settled. Without
        # this a hypothesis that briefly shortens would retract text we already
        # told downstream was safe.
        if hypothesis.startswith(self._previous[: self._stable_len]):
            stable_len = max(stable_len, self._stable_len)
        else:
            # The server rewrote text it had effectively settled. Trust the new
            # hypothesis over our bookkeeping and say so — repeated hits here
            # mean the derivation heuristic is wrong for this server.
            logger.debug("Qwen3ASR: stable prefix retracted by server revision")

        self._previous = hypothesis
        self._stable_len = min(stable_len, len(hypothesis))
        return PrefixUpdate(
            stable_prefix=self.stable_prefix, unstable_tail=self.unstable_tail
        )

    def _derive_stable_len(self, hypothesis: str) -> int:
        common = 0
        for a, b in zip(self._previous, hypothesis):
            if a != b:
                break
            common += 1
        if common == 0:
            return 0
        # Cut back to the last completed word: "quo" being shared between "quota"
        # and "quote" says nothing about the word itself.
        if common < len(hypothesis) and not hypothesis[common].isspace():
            cut = hypothesis.rfind(" ", 0, common)
            common = cut + 1 if cut >= 0 else 0
        return common


class Qwen3ASRService(BaseSttAdapter, WebsocketSTTService):
    """Streaming STT against a self-hosted Qwen3-ASR-1.7B WebSocket server.

    Both bases are load-bearing: ``BaseSttAdapter`` is the registry contract
    (a plain ``STTService``, so a future recogniser need not be a websocket),
    and ``WebsocketSTTService`` brings the ``WebsocketService`` mixin this
    client is written against — ``self._websocket``, ``_websocket_connect``,
    ``send_with_retry``, the reconnect loop. Without the mixin the first
    ``StartFrame`` dies on ``'super' object has no attribute '_connect'`` and
    the call runs deaf.

    Behaviour beyond the base class:

    * Holds one socket per call and reconnects with backoff on drop. A failed
      reconnect degrades the call (no transcripts) rather than ending it — the
      turn controller's ``max_delay`` still fires, so the agent stays responsive
      instead of hanging on a dead socket.
    * Streams audio only while the VAD gate is open, with a pre-roll so the onset
      is not clipped. This is the cost cascade: Silero decides when the expensive
      model runs.
    * Resamples the transport's audio to 16 kHz in one place (:mod:`audio_path`).
    * Reports the language the server detected (:attr:`detected_language`); this
      endpoint exposes no way to force it.
    * Tracks a stable prefix per utterance, exposed as :attr:`stable_prefix` and
      on every interim frame's ``metadata["stable_prefix"]``.
    """

    #: What this client assumes about a protocol with no specification. Logged
    #: per call from the backend that is actually selected, so swapping the
    #: recogniser swaps the caveats with it.
    protocol_assumptions: tuple[str, ...] = PROTOCOL_ASSUMPTIONS

    #: Measured against a live deployment; an organization may override any of
    #: these from its model row. ``tail_silence_seconds`` is zero because
    #: Qwen3-ASR ends an utterance with a newline of its own accord.
    capabilities: SttCapabilities = SttCapabilities(
        streams_during_speech=True,
        emits_completion_event=False,
        min_commit_seconds=MIN_COMMIT_SECONDS,
        tail_silence_seconds=0.0,
        reports_language=True,
        sample_rate=ASR_SAMPLE_RATE,
        accepts_language_hint=False,
    )

    @classmethod
    def from_config(
        cls, config: SttConfig, *, call_id: str, audio_path: AudioPath
    ) -> Qwen3ASRService:
        """Build a client from an organization's STT row."""
        return cls(
            ws_url=config.websocket_url(),
            api_key=config.model.provider.api_key,
            model=config.model.code,
            language=config.language or "en",
            session_id=call_id,
            audio_path=audio_path,
            **config.model.provider.options.get("client", {}),
        )

    def __init__(
        self,
        *,
        ws_url: str,
        api_key: str | None = None,
        language: str | Language = Language.EN,
        session_id: str = "",
        model: str = DEFAULT_ASR_MODEL,
        audio_path: AudioPath | None = None,
        preroll_ms: int = DEFAULT_PREROLL_MS,
        sample_rate: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the Qwen3-ASR client.

        Args:
            ws_url: WebSocket endpoint, e.g. ``ws://localhost:8100/v1/asr/stream``.
            api_key: Optional bearer token for the handshake.
            language: Language to force. Never auto-detected.
            session_id: Call correlation ID, sent in the ``start`` message.
            model: Served model name. Must match an id from the server's
                ``/v1/models`` or ``session.update`` is rejected.
            audio_path: Per-call converter. One is created if not supplied.
            preroll_ms: Audio retained while the gate is shut, replayed on open.
            sample_rate: Input rate override; normally taken from ``StartFrame``.
            **kwargs: Passed to :class:`WebsocketSTTService`.
        """
        # `settings` is the base class's store for model and language, and it
        # checks at start() that a service filled every field in. Keeping them
        # here rather than in private attributes is also what makes
        # `STTUpdateSettingsFrame` work — the router sends one per call to select
        # the language, and a private copy would never see it.
        super().__init__(
            sample_rate=sample_rate,
            settings=STTSettings(model=model, language=language),
            **kwargs,
        )
        self._ws_url = ws_url
        self._api_key = api_key
        self._session_id = session_id
        # Mirrors of settings.language in the two shapes the rest of the class
        # needs; refreshed by _update_settings().
        self._language_raw = self._raw_code(self._settings.language)
        self._language = self._coerce_language(self._settings.language)

        self._audio_path = audio_path or AudioPath(asr_sample_rate=ASR_SAMPLE_RATE)
        self._receive_task: asyncio.Task | None = None

        # VAD gate. Closed until Silero reports speech; reopened per turn.
        self._gate_open = False
        self._preroll_ms = preroll_ms
        self._preroll: deque[bytes] = deque()
        self._preroll_bytes = 0
        self._preroll_limit = int(ASR_SAMPLE_RATE * 2 * preroll_ms / 1000)

        self._tracker = StablePrefixTracker()
        self._utterance = UtteranceBuffer()
        # Raw delta stream for the current utterance, preamble included.
        self._raw = ""
        self._detected_language: str | None = None
        # Audio sent since the last commit, for the minimum-buffer padding.
        self._sent_bytes = 0

    # -- public surface ----------------------------------------------------

    @property
    def stable_prefix(self) -> str:
        """The settled part of the in-flight hypothesis.

        Downstream speculation (retrieval, prefill) must read this rather than an
        interim frame's full text, which is still being revised.
        """
        return self._tracker.stable_prefix

    @property
    def unstable_tail(self) -> str:
        """The still-revisable part of the in-flight hypothesis."""
        return self._tracker.unstable_tail

    @property
    def gate_open(self) -> bool:
        """Whether audio is currently being streamed to the server."""
        return self._gate_open

    def flush(self) -> str:
        """Return the accumulated transcript for the current utterance and clear it.

        Local bookkeeping only: it drains this client's buffer and does not wait
        for the server. The live pipeline consumes transcription frames rather
        than this snapshot. To request the server's final promptly, the service
        sends ``input_audio_buffer.commit`` on VAD stop, while acoustic turn
        detection and transcript finalization proceed concurrently.
        """
        text = self._utterance.text()
        self._utterance.clear()
        self._tracker.reset()
        return text

    @property
    def detected_language(self) -> str | None:
        """Language the server reported for the current utterance, if any.

        Normalised to a lowercase code ("ru") per the base contract; the raw
        preamble name is what the debug log shows.

        Observed, not commanded: this endpoint exposes no way to force it. A
        persistent disagreement with the call metadata is a routing signal.
        """
        if self._detected_language is None:
            return None
        return language_code(self._detected_language)

    # -- lifecycle ---------------------------------------------------------

    async def start(self, frame: StartFrame) -> None:
        """Open the socket when the pipeline starts."""
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame) -> None:
        """Close the socket on a graceful end."""
        await super().stop(frame)

    async def cancel(self, frame: CancelFrame) -> None:
        """Close the socket immediately."""
        await super().cancel(frame)

    async def _connect(self) -> None:
        await self._connect_websocket()
        await super()._connect()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(
                self._receive_task_handler(self._report_error)
            )

    async def _disconnect(self) -> None:
        await super()._disconnect()
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    async def _connect_websocket(self) -> None:
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return
            logger.debug(f"{self}: connecting to {self._ws_url}")
            headers = (
                {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
            )
            self._websocket = await self._websocket_connect(
                self._ws_url, additional_headers=headers
            )
            # Configuration is NOT sent here. The server opens with
            # `session.created`, and `session.update` before that arrives is
            # either ignored or answered with "Invalid audio data" once audio
            # starts. _handle_message sends it at the right moment.
            await self._call_event_handler("on_connected")
        except Exception as exc:  # noqa: BLE001
            # Deliberately not fatal. A call without transcripts is degraded; a
            # call that dies on connect is a dropped customer. The reconnect loop
            # in WebsocketService keeps trying underneath.
            logger.error(f"{self}: connect to {self._ws_url} failed: {exc}")
            self._websocket = None

    async def _disconnect_websocket(self) -> None:
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                # No teardown event exists in this protocol; closing the socket
                # is the whole shutdown. An invented `stop` just draws an
                # "unknown event" error on the way out.
                await self._websocket.close()
        except Exception as exc:  # noqa: BLE001 - closing on the way out, must not raise
            logger.warning(f"{self}: error closing websocket: {exc}")
        finally:
            if self._websocket:
                await self._call_event_handler("on_disconnected")
            self._websocket = None
            self._gate_open = False
            self._preroll.clear()
            self._preroll_bytes = 0

    # -- audio in ----------------------------------------------------------

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None]:
        """Feed one audio frame to the recogniser.

        Transcripts arrive asynchronously on the receive task, so nothing is
        yielded here — this only moves bytes.

        Args:
            audio: 16-bit mono PCM at the transport's sample rate.

        Yields:
            Nothing. Frames are pushed from :meth:`_handle_message`.
        """
        # Resample unconditionally, gate afterwards. The stream resampler carries
        # filter state between calls; skipping frames while the gate is shut
        # would splice discontinuous audio into its history and colour the first
        # frames of every turn.
        pcm = await self._audio_path.to_asr(audio, self.sample_rate)

        if not self._gate_open:
            self._buffer_preroll(pcm)
            yield None
            return

        if self._preroll:
            preroll = b"".join(self._preroll)
            self._preroll.clear()
            self._preroll_bytes = 0
            logger.trace(
                f"{self}: gate opened, replaying "
                f"{duration_of(preroll, ASR_SAMPLE_RATE) * 1000:.0f}ms of pre-roll"
            )
            await self._send_audio(preroll)

        await self._send_audio(pcm)
        yield None

    def _buffer_preroll(self, pcm: bytes) -> None:
        self._preroll.append(pcm)
        self._preroll_bytes += len(pcm)
        while self._preroll_bytes > self._preroll_limit and self._preroll:
            self._preroll_bytes -= len(self._preroll.popleft())

    async def _send_audio(self, pcm: bytes) -> None:
        if not self._websocket or self._websocket.state is not State.OPEN:
            return
        message = json.dumps(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            }
        )
        self._sent_bytes += len(pcm)
        await self.send_with_retry(message, self._report_error)

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if not self._websocket:
            return
        await self._websocket.send(json.dumps(payload))

    # -- gate --------------------------------------------------------------

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Drive the VAD gate off Silero's speech events.

        The gate opens when Silero reports speech and closes when the *turn*
        commits, not when Silero reports silence. Smart Turn rejects a good share
        of VAD stops as mid-turn pauses, so a gate tied to VAD would tear the
        stream in the middle of an utterance and hand the recogniser two
        fragments where the caller spoke one sentence.
        """
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._open_gate()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            # Ask the server for a final now; the turn may still be open, but the
            # transcript should be waiting when it commits.
            await self._request_server_finalize()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._close_gate()

        await super().process_frame(frame, direction)

    def _open_gate(self) -> None:
        if not self._gate_open:
            logger.trace(f"{self}: VAD gate open")
        self._gate_open = True

    def _close_gate(self) -> None:
        if self._gate_open:
            logger.trace(f"{self}: VAD gate closed")
        self._gate_open = False

    async def _request_server_finalize(self) -> None:
        """Commit the buffer, padding it to the server's minimum first.

        See :data:`MIN_COMMIT_SECONDS`. Below that threshold the server returns
        an empty stream rather than an error, so a short reply is silently lost —
        the caller hears the agent ignore them, which reads as the agent being
        broken rather than the ASR being picky.
        """
        if not self._websocket or self._websocket.state is not State.OPEN:
            return
        try:
            rate = self._audio_path.asr_sample_rate
            required = bytes_for_duration(MIN_COMMIT_SECONDS, rate)
            tail = bytes_for_duration(self.capabilities.tail_silence_seconds, rate)
            # Two independent demands: the server's minimum buffer, and (for
            # backends that need it) silence *after* the speech so the decoder
            # runs past the last word instead of stopping on it.
            shortfall = max(required - self._sent_bytes, tail)
            if shortfall > 0:
                logger.trace(
                    f"{self}: padding {shortfall} bytes of silence before commit "
                    f"({MIN_COMMIT_SECONDS}s minimum, "
                    f"{self.capabilities.tail_silence_seconds}s tail)"
                )
                await self._send_audio(b"\x00" * shortfall)
            await self._send_json({"type": "input_audio_buffer.commit"})
        except Exception as exc:  # noqa: BLE001 - a failed commit must not crash the call
            logger.warning(f"{self}: commit failed: {exc}")
        finally:
            self._sent_bytes = 0

    # -- transcripts out ---------------------------------------------------

    async def _receive_messages(self) -> None:
        """Read server messages until the socket closes."""
        if not self._websocket:
            return
        async for message in self._websocket:
            if isinstance(message, bytes):
                # TODO: the contract assumes the server never sends binary. If it
                # does (e.g. packed logits), decode it here.
                logger.debug(
                    f"{self}: ignoring unexpected binary message ({len(message)} bytes)"
                )
                continue
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"{self}: non-JSON message discarded: {message[:120]!r}")
                continue
            await self._handle_message(payload)

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        kind = payload.get("type")

        if kind == "transcription.delta":
            await self._handle_delta(payload.get("delta") or "")

        elif kind == "session.created":
            # The server is ready for configuration.
            logger.debug(f"{self}: session {payload.get('id')} created")
            await self._send_json(self._start_message())

        elif kind == "error":
            # `error` is a bare string here, unlike OpenAI's object. Handle both
            # so a server that fixes this later does not start crashing us.
            raw = payload.get("error")
            message = (
                raw
                if isinstance(raw, str)
                else (raw or {}).get("message", "unknown error")
            )
            logger.error(
                f"{self}: server error [{payload.get('code', '-')}]: {message}"
            )
            await self._report_error(ErrorFrame(f"{self}: {message}"))

        else:
            logger.debug(f"{self}: unhandled message type {kind!r}")

    async def _handle_delta(self, delta: str) -> None:
        """Fold one delta into the running transcript.

        Deltas are append-only and carry the preamble described in the module
        docstring, so the work here is stripping it and spotting the newline that
        stands in for the completion event the server never sends.
        """
        if not delta:
            return

        self._raw += delta
        finalized = self._raw.endswith("\n")

        language, text = self._parse(self._raw)
        if language and language != self._detected_language:
            self._detected_language = language
            logger.debug(f"{self}: detected language {language!r}")
        if not text:
            return

        if finalized:
            self._utterance.finals.append(text)
            self._utterance.partial = ""
            self._tracker.reset()
            self._raw = ""
            await self.push_frame(
                TranscriptionFrame(
                    text,
                    self._user_id,
                    time_now_iso8601(),
                    self._language,
                    finalized=True,
                )
            )
            await self.emit_stt_usage_metrics()
            return

        update = self._tracker.update(text)
        self._utterance.partial = text
        frame = InterimTranscriptionFrame(
            text, self._user_id, time_now_iso8601(), self._language
        )
        frame.metadata["stable_prefix"] = update.stable_prefix
        frame.metadata["unstable_tail"] = update.unstable_tail
        await self.push_frame(frame)

    @staticmethod
    def _parse(raw: str) -> tuple[str | None, str]:
        """Split the accumulated delta stream into detected language and transcript.

        Before ``<asr_text>`` arrives the whole buffer is still preamble, so
        there is nothing to show the caller yet.
        """
        marker = raw.find(ASR_TEXT_MARKER)
        if marker < 0:
            return None, ""
        head, text = raw[:marker], raw[marker + len(ASR_TEXT_MARKER) :]
        match = _PREAMBLE_RE.match(head)
        language = match.group("language") if match else None
        return language, text.strip()

    async def _update_settings(self, delta: STTSettings) -> dict[str, Any]:
        """Apply a settings delta, keeping the language mirrors in step.

        The base class writes the delta into ``self._settings``; the mirrors
        this class tags transcription frames with have to follow, or a call that
        switches language keeps labelling frames with the language it started
        in. No reconnect is needed: this endpoint auto-detects and the language
        is only carried on the frames (see PROTOCOL_ASSUMPTIONS).
        """
        changed = await super()._update_settings(delta)
        if "language" in changed:
            self._language_raw = self._raw_code(self._settings.language)
            self._language = self._coerce_language(self._settings.language)
            logger.debug(f"{self}: language set to {self._language_raw!r}")
        return changed

    # -- helpers -----------------------------------------------------------

    def _start_message(self) -> dict[str, Any]:
        """The ``session.update`` that configures the stream.

        ``model`` is top-level on purpose — nesting it under
        ``session.audio.input.transcription``, where OpenAI's schema puts it,
        is rejected with "Missing required field: model".
        """
        return {
            "type": "session.update",
            "model": self._settings.model,
            "session": {
                # Server-side endpointing off: Silero and the Smart Turn cascade
                # decide turn boundaries. Two endpointers is a bug, not redundancy.
                "turn_detection": None,
                "input_audio_format": "pcm16",
            },
        }

    @property
    def _language_code(self) -> str:
        # An unrecognised code still goes to the server verbatim: Pipecat's
        # Language enum and the server's language set need not agree, and
        # dropping the caller's language would silently re-enable auto-detection.
        return (
            self._language.value if self._language is not None else self._language_raw
        )

    @staticmethod
    def _raw_code(language: str | Language) -> str:
        return (
            language.value if isinstance(language, Language) else str(language).lower()
        )

    @staticmethod
    def _coerce_language(language: str | Language) -> Language | None:
        if isinstance(language, Language):
            return language
        try:
            return Language(language.lower())
        except ValueError:
            logger.warning(
                f"Qwen3ASR: unrecognised language {language!r}; sending as-is"
            )
            return None


SttAdapters[SttAdapterEnum.qwen3_asr] = Qwen3ASRService
