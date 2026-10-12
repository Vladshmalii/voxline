"""Qwen3-TTS client for vLLM-Omni's ``/v1/audio/speech`` endpoint.

Qwen3-TTS is served on an OpenAI-compatible route, but it is not OpenAI, and
Pipecat's :class:`OpenAITTSService` assumes it is in two ways that both break:

1. **It validates the voice against OpenAI's own list** (``alloy``, ``echo``,
   ``nova``, …) and refuses anything else *before* sending the request. Qwen3-TTS
   voices are ``vivian``, ``ryan``, ``serena`` and friends, so every request
   fails client-side with "voice is not supported".
2. **It never sends a language.** Qwen3-TTS takes an explicit ``language``, and
   it wants the language *name* — ``"English"``, not ``"en"``.

So this subclass replaces ``run_tts``. Everything else — the OpenAI client,
settings, metrics, the clause aggregator — is inherited.

Values below were verified against a live vLLM-Omni deployment rather than
assumed:

* **Voices** (9): ``aiden``, ``dylan``, ``eric``, ``ono_anna``, ``ryan``,
  ``serena``, ``sohee``, ``uncle_fu``, ``vivian``
* **Languages** (13): ``Auto``, ``Beijing_Dialect``, ``Chinese``, ``English``,
  ``French``, ``German``, ``Italian``, ``Japanese``, ``Korean``, ``Portuguese``,
  ``Russian``, ``Sichuan_Dialect``, ``Spanish``
* **Audio**: ``response_format: "pcm"`` returns raw 24 kHz mono PCM16, which is
  already Pipecat's OpenAI default rate, so no resampling is configured here.

Note the language list is narrower than Qwen3-ASR's 30 — the agent can
understand considerably more languages than it can speak.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Final

from loguru import logger
from openai import BadRequestError
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.openai.tts import OpenAITTSService, OpenAITTSSettings
from pipecat.utils.tracing.service_decorators import traced_tts
from pipecat.utils.types import assert_given

from src.application.engine.capabilities import TtsCapabilities
from src.application.engine.chunking import ClauseAggregator, WholeTurnAggregator
from src.application.engine.config import ChunkingConfig, TtsConfig
from src.application.engine.loudness import ChunkLoudnessMatcher
from src.common.enums.engine import ChunkingModeEnum, TtsAdapterEnum
from src.integrations.tts.base import BaseTtsAdapter, TtsAdapters

#: Voices the server accepts. Kept for the startup warning only — the value is
#: passed through untouched, so a server with a different set still works.
QWEN_TTS_VOICES: Final[frozenset[str]] = frozenset(
    {
        "aiden",
        "dylan",
        "eric",
        "ono_anna",
        "ryan",
        "serena",
        "sohee",
        "uncle_fu",
        "vivian",
    }
)

#: Language codes to the names Qwen3-TTS expects. Anything unmapped falls back to
#: ``Auto``, which lets the model infer from the text — a better failure than a
#: 400 that silences the agent mid-call.
LANGUAGE_NAMES: Final[dict[str, str]] = {
    "zh": "Chinese",
    "en": "English",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "es": "Spanish",
}

AUTO_LANGUAGE: Final[str] = "Auto"


def language_name(code: str | None) -> str:
    """Map a language code to the name Qwen3-TTS expects.

    Accepts full tags (``pt-BR``) by falling back to the base subtag.

    Args:
        code: Language code, or ``None``.

    Returns:
        A name from :data:`LANGUAGE_NAMES`, or ``"Auto"`` when unmapped.
    """
    if not code:
        return AUTO_LANGUAGE
    normalised = str(code).strip().lower().replace("_", "-")
    if normalised in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[normalised]
    return LANGUAGE_NAMES.get(normalised.split("-")[0], AUTO_LANGUAGE)


class _NoLoudnessMatching:
    """Stand-in when an organization turns level matching off."""

    reference = None

    def observe(self, pcm: bytes) -> None:
        """Ignore the chunk; nothing is being matched."""

    def match(self, pcm: bytes) -> bytes:
        """Return the audio untouched."""
        return pcm


class Qwen3TTSService(OpenAITTSService, BaseTtsAdapter):
    """Qwen3-TTS on vLLM-Omni, with clause-level chunking for the LLM overlap."""

    #: Measured against a live vLLM-Omni deployment. Time to first byte tracks
    #: input length (0.7s for 4 words, 3.8s for 37), so nothing arrives early;
    #: and the same sentence resynthesised comes back 2.4s, 2.5s, then 3.6s
    #: long with RMS between 2451 and 5025, with ``seed`` accepted and ignored.
    #: Hence: chunk to get first audio early, and match loudness across chunks.
    capabilities: TtsCapabilities = TtsCapabilities(
        streams_incrementally=False,
        deterministic=False,
        accepts_seed=False,
        sample_rate=24000,
    )

    @classmethod
    def from_config(
        cls, config: TtsConfig, chunking: ChunkingConfig
    ) -> Qwen3TTSService:
        """Build a synthesiser from an organization's TTS row."""
        return cls(
            base_url=config.model.provider.url,
            api_key=config.model.provider.api_key,
            settings=OpenAITTSSettings(
                model=config.model.code,
                voice=config.voice,
                # Without this the first turn of every call is synthesised with
                # `language: Auto` and only a mid-call switch ever sets one.
                language=config.language,
                speed=config.speed,
                instructions=config.instructions,
            ),
            chunk_min_words=chunking.min_words,
            chunk_max_words=chunking.max_words,
            clause_cuts=chunking.clause_cuts,
            chunking=chunking.mode == ChunkingModeEnum.clause,
            match_loudness=chunking.match_loudness,
        )

    def __init__(
        self,
        *,
        chunk_min_words: int = 8,
        chunk_max_words: int | None = None,
        clause_cuts: int = 1,
        chunking: bool = True,
        match_loudness: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialise the service.

        Args:
            chunk_min_words: Words to accumulate before a clause boundary may end
                a chunk. See :mod:`services.chunking`.
            chunk_max_words: Hard ceiling before a chunk is cut regardless of
                punctuation. Defaults to a multiple of ``chunk_min_words``.
            clause_cuts: Chunks per turn that may end at a clause rather than a
                sentence. Only the first is on the latency path.
            chunking: Whether to stream the reply to TTS in chunks. ``False``
                synthesises each reply in a single request — one voice per turn,
                at the cost of the whole LLM→TTS overlap.
            match_loudness: Scale later chunks to the first chunk's level.
            **kwargs: Passed to :class:`OpenAITTSService`.
        """
        super().__init__(**kwargs)
        # Pipecat's TTSService hard-codes a SimpleTextAggregator in its
        # constructor and exposes no setter in 1.7, so it is swapped afterwards.
        # Sentence-only chunking would delay first audio to the end of the
        # sentence; see services/chunking.py.
        if chunking:
            self._text_aggregator = ClauseAggregator(
                min_words=chunk_min_words,
                max_words=chunk_max_words,
                clause_cuts=clause_cuts,
                aggregation_type=self._text_aggregation_mode,
            )
        else:
            self._text_aggregator = WholeTurnAggregator(
                aggregation_type=self._text_aggregation_mode
            )
            logger.info(
                "TTS chunking off: each reply is synthesised in one request, so "
                "first audio waits for the whole reply to be generated"
            )
        # Per call, because the reference is the loudness this caller first
        # heard. The router builds one service per call, so the lifetime is
        # already right.
        self._loudness = (
            ChunkLoudnessMatcher() if match_loudness else _NoLoudnessMatching()
        )

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame]:
        """Synthesise one chunk of text.

        Replaces the parent implementation to drop OpenAI's voice whitelist and
        to send Qwen3-TTS's ``language`` parameter.

        Args:
            text: The text to speak.
            context_id: Context ID for tracking the resulting audio frames.

        Yields:
            ``TTSAudioRawFrame`` chunks, or an ``ErrorFrame`` on failure.
        """
        voice = assert_given(self._settings.voice)
        if not voice:
            yield ErrorFrame(error="Qwen3-TTS voice must be specified")
            return

        params: dict[str, Any] = {
            "input": text,
            "model": self._settings.model,
            "voice": voice,
            "response_format": "pcm",
            # `language` is not part of OpenAI's schema, so it travels in
            # extra_body rather than being dropped by the client.
            "extra_body": {"language": language_name(self._settings.language)},
        }
        if self._settings.instructions:
            params["instructions"] = self._settings.instructions
        if self._settings.speed:
            params["speed"] = self._settings.speed

        try:
            async with self._client.audio.speech.with_streaming_response.create(
                **params
            ) as r:
                if r.status_code != 200:
                    error = await r.text()
                    logger.error(f"{self} TTS failed (status {r.status_code}): {error}")
                    yield ErrorFrame(error=f"Qwen3-TTS error {r.status_code}: {error}")
                    return

                await self.start_tts_usage_metrics(text)

                # The first chunk of the call is streamed out as it arrives and
                # sets the loudness reference: nothing may be buffered on the
                # path to first audio. Every later chunk is collected in full
                # first, because matching its level needs its RMS, and the wait
                # is hidden — the caller is still hearing the previous chunk.
                # The server is not incremental anyway (time to first byte
                # tracks input length), so this costs the download tail, ~50 ms.
                if self._loudness.reference is None:
                    first = bytearray()
                    async for chunk in r.iter_bytes(self.chunk_size):
                        if chunk:
                            await self.stop_ttfb_metrics()
                            first += chunk
                            yield TTSAudioRawFrame(
                                chunk, self.sample_rate, 1, context_id=context_id
                            )
                    self._loudness.observe(bytes(first))
                    return

                audio = bytearray()
                async for chunk in r.iter_bytes(self.chunk_size):
                    if chunk:
                        # First byte back ends time-to-first-byte for this chunk;
                        # the caller is already hearing the previous one.
                        await self.stop_ttfb_metrics()
                        audio += chunk

                matched = self._loudness.match(bytes(audio))
                for start in range(0, len(matched), self.chunk_size):
                    yield TTSAudioRawFrame(
                        matched[start : start + self.chunk_size],
                        self.sample_rate,
                        1,
                        context_id=context_id,
                    )
        except BadRequestError as e:
            # Most often a voice or language the server does not recognise.
            logger.error(f"{self} rejected by server: {e}")
            yield ErrorFrame(error=f"Qwen3-TTS rejected the request: {e}")


TtsAdapters[TtsAdapterEnum.qwen3_tts] = Qwen3TTSService
