"""OpenRouter speech: one key in front of every synthesiser the aggregator resells.

The mirror of the recogniser in this project's OpenRouter pair, and it buys the
same thing — ``deepgram/aura-2``, ``mistralai/voxtral-mini-tts-2603``,
``hexgrad/kokoro-82m``, Gemini and MiniMax are a ``model.code`` edit rather than
an adapter each.

``POST {root}/audio/speech`` *is* OpenAI-compatible, unlike the transcription
route next to it, so Pipecat's :class:`OpenAITTSService` client, settings and
metrics are inherited whole. Only :meth:`run_tts` is replaced, for three
reasons:

1. **The voice whitelist.** The parent validates ``voice`` against OpenAI's own
   list before sending, so ``en_paul_happy`` or ``af_bella`` fails client-side
   with "voice is not supported". Voices here are namespaced by whichever vendor
   the slug routes to, and the authoritative set is ``supported_voices`` on
   ``GET /models?output_modalities=speech`` — not anything this module could
   hard-code.
2. **The sample rate is in the response, not in the contract.** ``pcm`` comes
   back as a bare bytestream with the rate in the content type
   (``audio/pcm;rate=24000;channels=1``). It is the upstream vendor's rate, so
   one account can serve 24 kHz on one turn and 16 kHz on the next; the value is
   read per response and resampled to the pipeline's rate. Assuming a constant
   here is how a voice ends up a chipmunk.
3. **Provider routing.** OpenRouter's ``provider`` block — pinning a vendor,
   ordering fallbacks, per-vendor passthrough such as OpenAI's ``instructions``
   — is not in OpenAI's schema and has to travel in ``extra_body`` or be dropped.

What it does not do
-------------------
**It does not stream.** There is no incremental mode on this endpoint: the
request returns when the clip is synthesised. So ``streams_incrementally`` is
false and clause chunking is not an optimisation but the only thing keeping time
to first audio off the length of the whole reply — the same position Qwen3-TTS
is in, for the same reason.

And because a chunked reply is several requests to a model that need not be
deterministic between them, chunk loudness is matched to the first chunk of the
call, exactly as on the other non-streaming synthesiser here. Whether a given
slug actually drifts has not been measured; matching a backend that does not
drift costs nothing, and the reverse is audible.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Final

from loguru import logger
from openai import APIError
from pipecat.frames.frames import ErrorFrame, Frame, StartFrame, TTSAudioRawFrame
from pipecat.services.openai.tts import OpenAITTSService, OpenAITTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts
from pipecat.utils.types import assert_given

from src.application.engine.capabilities import TtsCapabilities
from src.application.engine.chunking import ClauseAggregator, WholeTurnAggregator
from src.application.engine.config import ChunkingConfig, TtsConfig
from src.application.engine.loudness import ChunkLoudnessMatcher
from src.common.enums.engine import ChunkingModeEnum, TtsAdapterEnum
from src.integrations.tts.base import BaseTtsAdapter, TtsAdapters
from src.integrations.tts.deepgram import voice_language
from src.utils.openrouter import api_root, headers, pcm_sample_rate

#: Audio format requested. ``pcm`` rather than ``mp3`` because the pipeline
#: wants samples, and decoding mp3 to get them back would add latency to buy
#: bandwidth nobody here is short of.
RESPONSE_FORMAT: Final[str] = "pcm"

#: Rate assumed when a response omits it from its content type. OpenAI's TTS
#: rate, which is what most of this catalogue is; it is a fallback for a
#: malformed header, not a claim about the vendor.
FALLBACK_SAMPLE_RATE: Final[int] = 24000

#: Model used when a row leaves ``code`` empty. Aura-2 because it is the widest
#: multilingual voice set in the catalogue (90 voices, language in the suffix),
#: which is what an agent configured per language needs; the price is per
#: character of input, so a default that is never used costs nothing.
#:
#: Slugs must be given in full and vendor-prefixed. Checked against the live
#: catalogue rather than copied from a guide: OpenAI publishes a TTS model, but
#: OpenRouter does not resell one, so ``openai/gpt-4o-mini-tts`` — the obvious
#: default — is not a model here at all.
DEFAULT_TTS_MODEL: Final[str] = "deepgram/aura-2"

#: Fields of OpenRouter's speech request that OpenAI's schema has no room for,
#: taken from the provider row and sent in ``extra_body``. ``provider`` is the
#: routing and passthrough block; ``input_references`` carries a voice-cloning
#: sample for the endpoints that support one.
PASSTHROUGH_FIELDS: Final[tuple[str, ...]] = ("provider", "input_references")


class _NoLoudnessMatching:
    """Stand-in when an organization turns level matching off."""

    reference = None

    def observe(self, pcm: bytes) -> None:
        """Ignore the chunk; nothing is being matched."""

    def match(self, pcm: bytes) -> bytes:
        """Return the audio untouched."""
        return pcm


class OpenRouterTTSAdapter(OpenAITTSService, BaseTtsAdapter):
    """Speech through OpenRouter's aggregated synthesiser catalogue."""

    #: Read off OpenRouter's documented contract, not measured against traffic.
    #:
    #: ``sample_rate`` is the declared default only. The rate that is actually
    #: used comes from each response's content type, because it belongs to
    #: whichever vendor the slug routed to; see the module docstring.
    #:
    #: ``deterministic`` is false because this is a catalogue, not a model: the
    #: same row can route to an autoregressive codec model that redraws pace and
    #: level per request. Claiming determinism on behalf of vendors chosen at
    #: request time would be claiming it for all of them.
    capabilities: TtsCapabilities = TtsCapabilities(
        streams_incrementally=False,
        deterministic=False,
        accepts_seed=False,
        sample_rate=FALLBACK_SAMPLE_RATE,
        max_input_chars=None,
    )

    @classmethod
    def from_config(
        cls, config: TtsConfig, chunking: ChunkingConfig
    ) -> OpenRouterTTSAdapter:
        """Build a synthesiser from an organization's TTS row."""
        provider = config.model.provider
        if not provider.api_key:
            logger.warning(
                "openrouter tts: no api_key on the provider row; "
                "every synthesis will come back 401"
            )
        options = provider.options
        # Checked against the Aura naming convention only — the default model
        # here is `deepgram/aura-2` and every other vendor's voice ids are left
        # unparsed, since a wrong guess is worse than no check.
        spoken = voice_language(config.voice)
        if (
            spoken
            and config.language
            and spoken != config.language.split("-")[0].lower()
        ):
            logger.warning(
                f"openrouter tts: voice {config.voice!r} looks like it speaks {spoken!r} "
                f"but the call runs in {config.language!r}; this route has no language "
                "parameter, so the voice is the only thing that decides"
            )
        return cls(
            base_url=api_root(provider.url),
            api_key=provider.api_key,
            # The row's rate is what the pipeline gets; whatever the vendor
            # returns is resampled to it.
            sample_rate=config.sample_rate,
            settings=OpenAITTSSettings(
                model=config.model.code or DEFAULT_TTS_MODEL,
                voice=config.voice,
                # No language field exists on this endpoint — the voice carries
                # it, which is why a language row overrides the voice. Kept on
                # settings so the switcher's update lands somewhere honest and
                # the mismatch warning below can be made.
                language=config.language,
                speed=config.speed,
                instructions=config.instructions,
            ),
            request_headers=headers(provider.api_key, options),
            passthrough={
                key: options[key] for key in PASSTHROUGH_FIELDS if key in options
            },
            chunk_min_words=chunking.min_words,
            chunk_max_words=chunking.max_words,
            clause_cuts=chunking.clause_cuts,
            chunking=chunking.mode == ChunkingModeEnum.clause,
            match_loudness=chunking.match_loudness,
        )

    def __init__(
        self,
        *,
        request_headers: dict[str, str] | None = None,
        passthrough: dict[str, Any] | None = None,
        sample_rate: int | None = None,
        chunk_min_words: int = 8,
        chunk_max_words: int | None = None,
        clause_cuts: int = 1,
        chunking: bool = True,
        match_loudness: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialise the service.

        Args:
            request_headers: Attribution headers from
                :func:`src.utils.openrouter.headers`. The SDK already sends the
                key, so only the non-authorization entries are used.
            passthrough: OpenRouter-only request fields, sent in ``extra_body``.
            sample_rate: Rate the pipeline gets. Applied after construction
                rather than through :class:`OpenAITTSService`, which warns that
                "OpenAI TTS only supports 24000Hz" for anything else — true of
                OpenAI, false of a catalogue whose vendors return several rates
                and which this class resamples on the way out. The warning would
                fire on every correctly configured 8 kHz telephony row.
            chunk_min_words: Words to accumulate before a clause boundary may end
                a chunk. See :mod:`src.application.engine.chunking`.
            chunk_max_words: Hard ceiling before a chunk is cut regardless of
                punctuation.
            clause_cuts: Chunks per turn that may end at a clause rather than a
                sentence. Only the first is on the latency path.
            chunking: Whether to stream the reply to TTS in chunks. ``False``
                synthesises each reply in one request — one draw of the voice per
                turn, paid for with the whole LLM→TTS overlap.
            match_loudness: Scale later chunks to the first chunk's level.
            **kwargs: Passed to :class:`OpenAITTSService`.
        """
        super().__init__(**kwargs)
        if sample_rate:
            # Read by TTSService.setup() to fix the output rate; see the arg doc.
            self._init_sample_rate = sample_rate
        # Authorization is the SDK's job; what it does not know about is the
        # attribution pair, which decides how this tenant's traffic is labelled.
        self._extra_headers = {
            key: value
            for key, value in (request_headers or {}).items()
            if key.lower() not in ("authorization", "content-type")
        }
        self._passthrough = passthrough or {}
        # Pipecat's TTSService fixes a SimpleTextAggregator in its constructor
        # and exposes no setter, so it is swapped afterwards — as in every
        # adapter here. Sentence-only chunking would hold first audio until the
        # end of the sentence.
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
        # heard. One service per call, so the lifetime is already right.
        self._loudness = (
            ChunkLoudnessMatcher() if match_loudness else _NoLoudnessMatching()
        )
        # Warned about once rather than per chunk: a rate that keeps changing is
        # worth one line, not one per sentence spoken.
        self._reported_rate: int | None = None

    async def start(self, frame: StartFrame) -> None:
        """Start the service without OpenAI's fixed-24kHz warning.

        ``OpenAITTSService.start()`` re-checks the sample rate itself and
        warns whenever it isn't 24 kHz, which would fire on every correctly
        configured telephony row — the exact false alarm the ``sample_rate``
        constructor argument above was written to avoid. Going through the
        grandparent runs the same startup, minus that check.
        """
        await TTSService.start(self, frame)

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame]:
        """Synthesise one chunk of text.

        Args:
            text: The text to speak.
            context_id: Context ID for tracking the resulting audio frames.

        Yields:
            ``TTSAudioRawFrame`` chunks, or an ``ErrorFrame`` on failure.
        """
        voice = assert_given(self._settings.voice)
        if not voice:
            # OpenRouter requires it, and there is no default worth inventing:
            # the valid set depends on the vendor the slug routes to.
            yield ErrorFrame(error="OpenRouter TTS requires a voice")
            return

        params: dict[str, Any] = {
            "input": text,
            "model": self._settings.model,
            "voice": voice,
            "response_format": RESPONSE_FORMAT,
        }
        if self._settings.instructions:
            params["instructions"] = self._settings.instructions
        if self._settings.speed:
            # Honoured by OpenAI's models; other vendors accept and ignore it.
            params["speed"] = self._settings.speed
        if self._passthrough:
            params["extra_body"] = dict(self._passthrough)
        if self._extra_headers:
            params["extra_headers"] = self._extra_headers

        try:
            async with self._client.audio.speech.with_streaming_response.create(
                **params
            ) as r:
                if r.status_code != 200:
                    error = await r.text()
                    logger.error(f"{self} TTS failed (status {r.status_code}): {error}")
                    yield ErrorFrame(
                        error=f"OpenRouter TTS error {r.status_code}: {error}"
                    )
                    return

                await self.start_tts_usage_metrics(text)
                source_rate = self._source_rate(r.headers.get("content-type"))

                # The first chunk of the call is streamed out as it arrives and
                # sets the loudness reference: nothing may be buffered on the
                # path to first audio. Later chunks are collected in full,
                # because matching a level needs the chunk's RMS, and the wait is
                # hidden behind the previous chunk still playing. The endpoint is
                # not incremental anyway, so this costs the download tail only.
                if self._loudness.reference is None:
                    first = bytearray()
                    async for chunk in r.iter_bytes(self.chunk_size):
                        if not chunk:
                            continue
                        await self.stop_ttfb_metrics()
                        pcm = await self._to_pipeline_rate(chunk, source_rate)
                        if not pcm:
                            continue
                        first += pcm
                        yield TTSAudioRawFrame(
                            pcm, self.sample_rate, 1, context_id=context_id
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

                resampled = await self._to_pipeline_rate(bytes(audio), source_rate)
                matched = self._loudness.match(resampled)
                for start in range(0, len(matched), self.chunk_size):
                    yield TTSAudioRawFrame(
                        matched[start : start + self.chunk_size],
                        self.sample_rate,
                        1,
                        context_id=context_id,
                    )
        except APIError as e:
            # Most often an unknown slug, or a voice the routed vendor does not
            # have — the two mistakes a row can make that this class cannot
            # catch locally, precisely because the valid sets are the vendor's.
            logger.error(f"{self} rejected by OpenRouter: {e}")
            yield ErrorFrame(error=f"OpenRouter rejected the request: {e}")

    def _source_rate(self, content_type: str | None) -> int:
        """The rate this response's PCM is in.

        Args:
            content_type: The response's ``Content-Type``.

        Returns:
            The declared rate, or :data:`FALLBACK_SAMPLE_RATE` when the header
            carries none — a malformed header is not a reason to go silent.
        """
        rate = pcm_sample_rate(content_type)
        if rate is None:
            rate = FALLBACK_SAMPLE_RATE
            if self._reported_rate is None:
                logger.warning(
                    f"{self}: no rate in content-type {content_type!r}; "
                    f"assuming {FALLBACK_SAMPLE_RATE} Hz"
                )
        if rate != self._reported_rate:
            logger.debug(
                f"{self}: vendor returned {rate} Hz, pipeline wants {self.sample_rate} Hz"
            )
            self._reported_rate = rate
        return rate

    async def _to_pipeline_rate(self, pcm: bytes, source_rate: int) -> bytes:
        """Resample vendor audio to the rate the pipeline was started with."""
        if not pcm or source_rate == self.sample_rate:
            return pcm
        return await self._resampler.resample(pcm, source_rate, self.sample_rate)


TtsAdapters[TtsAdapterEnum.openrouter] = OpenRouterTTSAdapter
