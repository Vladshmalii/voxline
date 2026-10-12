"""Deepgram Listen: the second hosted recogniser, and the one with knobs.

Where Cartesia exposes a handful of query parameters, Deepgram exposes several
dozen — endpointing, utterance-end timing, keyterm boosting, redaction, smart
formatting. None of them belong in this module: an organization's model row
carries them under ``provider.options["params"]`` and they are handed to the
vendor client as-is, so tuning a deployment is a row edit, not a release.

What this adapter owns is the seam the registry contract defines:

* ``from_config`` — one client per call, built from the organization's row.
* the 16 kHz conversion through the call's :class:`AudioPath`, because the
  session announces a rate in its query string and the transport may be an
  8 kHz phone leg.
* the local transcript buffer :meth:`flush` answers the turn controller from.
* :attr:`detected_language`, which Deepgram reports per alternative only when
  the row asks for multilingual transcription (``language=multi`` on a nova-3
  model) and omits otherwise — hence the capability default below.

Turn-taking stays where it belongs. Deepgram has its own endpointing and its
own ``UtteranceEnd`` event; this adapter subscribes to neither, and the VAD stop
that Pipecat turns into a ``Finalize`` is the only thing that closes an
utterance early. Two endpointers is a bug, not redundancy — an organization
that wants Deepgram's can still set ``endpointing`` through the row, and the
capability flag below is what tells the engine it did.

Every capability here is read off Deepgram's documentation and the Pipecat
client, **not** measured against a live account.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any, Final

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transcriptions.language import Language

from src.application.engine.audio import ASR_SAMPLE_RATE, AudioPath
from src.application.engine.capabilities import SttCapabilities
from src.application.engine.config import SttConfig
from src.common.enums.engine import SttAdapterEnum
from src.integrations.stt.base import BaseSttAdapter, SttAdapters, UtteranceBuffer

#: Served model when the row leaves ``code`` empty. ``nova-3-general`` is
#: Pipecat's default and the one the query parameters below are documented for.
DEFAULT_STT_MODEL: Final[str] = "nova-3-general"

#: What this client assumes that the protocol does not state.
PROTOCOL_ASSUMPTIONS: Final[tuple[str, ...]] = (
    "an is_final result closes that segment, and a turn may be several of them",
    (
        "the server's own endpointing is left at the account default and is not "
        "used as a turn boundary; VAD stop sends Finalize instead"
    ),
    (
        "an alternative without a languages field means the model does not detect "
        "language, not that detection failed"
    ),
)


def _is_known_language(code: str) -> bool:
    """Whether Pipecat's ``Language`` enum will accept this code."""
    try:
        Language(str(code))
    except ValueError:
        return False
    return True


def _without_language(message: Any) -> Any:
    """A copy of a result with its language field cleared.

    Pipecat's handler calls ``Language(code)`` unguarded, so a code its enum
    does not list raises inside the vendor client and the whole result is
    lost — transcript included. ``multi`` is exactly such a code, and exactly
    what Deepgram's multilingual model reports, so this is not a hypothetical.

    The language has already been recorded by the time this runs and the frame
    is tagged on the way out, so the copy costs nothing. It is a copy rather
    than a mutation because the SDK's models are frozen.

    Args:
        message: The result message from the SDK.

    Returns:
        An equivalent message whose first alternative has no ``languages``.
    """
    channel = message.channel
    alternatives = list(channel.alternatives)
    alternatives[0] = alternatives[0].model_copy(update={"languages": None})
    return message.model_copy(
        update={"channel": channel.model_copy(update={"alternatives": alternatives})}
    )


class DeepgramSTTAdapter(BaseSttAdapter, DeepgramSTTService):
    """Deepgram Listen streaming transcription, as one of the engine's recognisers.

    Unlike the realtime clients in this package, the vendor class is not built
    on Pipecat's websocket mixin — it drives Deepgram's own SDK client, which
    owns the socket, the reconnects and the keepalives. That is why this class
    pairs ``BaseSttAdapter`` with a plain ``STTService`` and adds nothing to
    the transport.
    """

    protocol_assumptions: tuple[str, ...] = PROTOCOL_ASSUMPTIONS

    #: Documented behaviour, not measured behaviour — see the module docstring.
    #:
    #: ``min_commit_seconds`` and ``tail_silence_seconds`` are zero for the same
    #: reason as Cartesia's: there is no commit to pad, results stream and
    #: finals arrive on their own.
    #:
    #: ``reports_language`` is false by default because a plain Deepgram model
    #: does not report one — the field only appears when the row asks for
    #: multilingual transcription (``params: {"language": "multi"}``). An
    #: organization that does should turn the capability on from the same row;
    #: :attr:`detected_language` reads the field either way.
    capabilities: SttCapabilities = SttCapabilities(
        streams_during_speech=True,
        emits_completion_event=True,
        min_commit_seconds=0.0,
        tail_silence_seconds=0.0,
        reports_language=False,
        server_turn_detection=False,
        sample_rate=ASR_SAMPLE_RATE,
        accepts_language_hint=True,
    )

    @classmethod
    def from_config(
        cls, config: SttConfig, *, call_id: str, audio_path: AudioPath
    ) -> DeepgramSTTAdapter:
        """Build a client from an organization's STT row.

        ``provider.options["params"]`` is passed straight through to the
        vendor client: keys it declares (``endpointing``, ``utterance_end_ms``,
        ``keyterm``, ``smart_format``, …) become settings, anything else becomes
        a query parameter. That is deliberate — Deepgram adds parameters faster
        than this repository would add columns for them.
        """
        provider = config.model.provider
        if not provider.api_key:
            logger.warning(
                f"deepgram stt: no api_key on provider {provider.url!r}; "
                "the handshake will be rejected"
            )
        settings = DeepgramSTTService.Settings.from_mapping(
            {
                "model": config.model.code or DEFAULT_STT_MODEL,
                "language": config.language or "en",
                **provider.options.get("params", {}),
            }
        )
        return cls(
            api_key=provider.api_key or "",
            # The vendor client derives both its ws and http endpoints from
            # this and falls back to Deepgram's own hosts when it is empty,
            # which is what a row pointing at the public API leaves it as.
            base_url=provider.url or "",
            settings=settings,
            encoding="linear16",
            # The rate the session announces, and the rate this adapter
            # converts every frame to. Not the transport's rate.
            sample_rate=ASR_SAMPLE_RATE,
            audio_path=audio_path,
            **provider.options.get("client", {}),
        )

    def __init__(self, *, audio_path: AudioPath | None = None, **kwargs: Any) -> None:
        """Initialise the client.

        Args:
            audio_path: The call's converters, shared with the transport. One is
                created if not supplied.
            **kwargs: Passed to :class:`DeepgramSTTService`.
        """
        super().__init__(**kwargs)
        self._audio_path = audio_path or AudioPath(asr_sample_rate=ASR_SAMPLE_RATE)
        self._transport_sample_rate = ASR_SAMPLE_RATE
        self._utterance = UtteranceBuffer()
        self._detected_language: str | None = None
        #: Wall-clock time of the most recent VAD speech start, for diagnosing
        #: how long Deepgram takes to emit a result relative to VAD activity.
        self._vad_speech_started_at: float | None = None

    # -- public surface ----------------------------------------------------

    def flush(self) -> str:
        """Return the transcript accumulated for the current turn and clear it."""
        text = self._utterance.text()
        self._utterance.clear()
        return text

    @property
    def detected_language(self) -> str | None:
        """Language of the last result that carried one, as a lowercase code."""
        return self._detected_language

    # -- audio in ----------------------------------------------------------

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Note the transport's rate before anything connects.

        Read from the setup rather than the ``StartFrame``, whose copy is
        deprecated since Pipecat 1.8.0.
        """
        self._transport_sample_rate = setup.audio_in_sample_rate or ASR_SAMPLE_RATE
        await super().setup(setup)

    async def _handle_vad_user_started_speaking(
        self, frame: VADUserStartedSpeakingFrame
    ) -> None:
        """Track when VAD last saw speech start, for the result-timing log below."""
        await super()._handle_vad_user_started_speaking(frame)
        self._vad_speech_started_at = time.time()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None]:
        """Convert one frame to the rate the session announced, then send it.

        Args:
            audio: 16-bit mono PCM at the transport's rate.

        Yields:
            Whatever the vendor service yields — nothing, in practice; results
            arrive on its connection handler.
        """
        pcm = await self._audio_path.to_asr(audio, self._transport_sample_rate)
        if not pcm:
            # The stream resampler primes its filter on the first frame and
            # returns nothing. An empty media message is not a thing to send.
            yield None
            return
        async for frame in super().run_stt(pcm):
            yield frame

    # -- transcripts out ---------------------------------------------------

    async def _on_message(self, message: Any) -> None:
        """Record the result locally, then let the vendor service push it.

        Mostly reads the message — unlike the Cartesia adapter, which is handed
        a plain dict it can tag in place, this one receives a typed SDK object,
        so the language fallback happens on the way out in :meth:`push_frame`.
        The one thing it does rewrite is a language code the vendor client
        cannot parse; see :func:`_without_language`.
        """
        alternatives = getattr(getattr(message, "channel", None), "alternatives", None)
        if alternatives:
            alternative = alternatives[0]
            languages = getattr(alternative, "languages", None)
            if languages:
                # Recorded as reported. A value like "multi" matches no
                # configured language, so it can never trigger a switch — which
                # is the right outcome, since it names no language to switch to.
                self._detected_language = str(languages[0]).strip().lower()
                if not _is_known_language(languages[0]):
                    logger.debug(
                        f"{self}: {languages[0]!r} is not a language the client can parse; "
                        "passing the result on without it"
                    )
                    message = _without_language(message)
            text = (getattr(alternative, "transcript", "") or "").strip()
            if text:
                since_vad_start = (
                    f"{time.time() - self._vad_speech_started_at:.2f}s"
                    if self._vad_speech_started_at is not None
                    else "unknown"
                )
                if getattr(message, "is_final", False):
                    self._utterance.finals.append(text)
                    self._utterance.partial = ""
                    logger.debug(
                        f"{self}: final result, {len(text)} chars, "
                        f"{since_vad_start} since VAD speech start"
                    )
                else:
                    self._utterance.partial = text
                    logger.debug(
                        f"{self}: interim result, {len(text)} chars, "
                        f"{since_vad_start} since VAD speech start"
                    )
        await super()._on_message(message)

    async def push_frame(
        self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        """Tag an untagged transcript with the call's language on its way out.

        Deepgram only labels a result when the model detects language, so
        without this most calls would push transcripts with no language at all
        and every consumer downstream would have to guess what the call was
        routed with.
        """
        if (
            isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame))
            and frame.language is None
            and self._settings.language
        ):
            frame.language = self._settings.language
        await super().push_frame(frame, direction)


SttAdapters[SttAdapterEnum.deepgram] = DeepgramSTTAdapter
