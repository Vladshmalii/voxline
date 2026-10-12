"""Cartesia Sonic TTS: the streaming synthesiser, behind the same registry.

Qwen3-TTS returns a whole clip per request, so everything around it — clause
chunking, loudness matching across chunks — exists to hide that. Cartesia is
the opposite kind of backend, and the adapter is shaped by the difference:

=======================  ============================  =========================
                         Qwen3-TTS (vLLM)              Cartesia Sonic
=======================  ============================  =========================
streaming                no; time to first byte        yes, over a WebSocket
                         tracks input length
one turn                 N independent requests, one   one audio context the
                         draw of the speaker each      chunks ``continue``
level across chunks      redrawn per request, matched  one context, so nothing
                         by ``ChunkLoudnessMatcher``   to match
text in                  one string per request        token-by-token
=======================  ============================  =========================

What that means for :class:`ChunkingConfig`:

* ``mode=clause`` hands the text to Cartesia token by token (Pipecat's
  ``TextAggregationMode.TOKEN``) and lets the server decide when to start
  speaking. ``min_words``, ``max_words`` and ``clause_cuts`` tune the *client*
  side of a non-streaming backend and have nothing to do here; they are logged
  as inert at build time rather than silently ignored.

  That path leaves ``max_buffer_delay_ms`` unset, which means Cartesia's own
  3000 ms default. It is a **ceiling, not a delay**: the model starts speaking
  as soon as it has enough context, and the window exists to stop single-token
  inputs producing choppy prosody. The vendor recommends against lowering it,
  so the row can (``provider.options``) and this module does not.
* ``mode=whole_turn`` still means what it means everywhere else — the reply is
  synthesised once, after the LLM has finished — and installs the same
  :class:`WholeTurnAggregator` the other synthesiser uses.
* ``match_loudness`` is inert for the reason in the table: one context per turn.

``TtsConfig`` maps onto Cartesia's own knobs like this:

    voice         → ``voice.id`` (a Cartesia voice UUID, not a name)
    speed         → ``generation_config.speed``, clamped to the accepted range
    instructions  → ``generation_config.emotion``, when it names one; there is
                    no free-text instruction field in this API
    sample_rate   → ``output_format.sample_rate`` (raw PCM16 out)

and ``provider.options`` carries what has no column: ``emotion``, ``volume``,
``pronunciation_dict_id``, ``max_buffer_delay_ms``.
"""

from __future__ import annotations

from typing import Any, Final

from loguru import logger
from pipecat.services.cartesia.tts import (
    CartesiaEmotion,
    CartesiaTTSService,
    GenerationConfig,
)
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TextAggregationMode
from pipecat.transcriptions.language import Language
from pipecat.utils.types import is_given

from src.application.engine.capabilities import TtsCapabilities
from src.application.engine.chunking import WholeTurnAggregator
from src.application.engine.config import ChunkingConfig, TtsConfig
from src.common.enums.engine import ChunkingModeEnum, TtsAdapterEnum
from src.integrations.tts.base import BaseTtsAdapter, TtsAdapters
from src.utils.url import websocket_url

#: Where Cartesia's synthesiser lives when a provider row leaves the URL empty.
DEFAULT_TTS_URL: Final[str] = "wss://api.cartesia.ai/tts/websocket"

#: Route appended to an ``http(s)://`` provider URL, so one row can serve every
#: kind of model and a reverse-proxy prefix survives.
TTS_WS_ROUTE: Final[str] = "/tts/websocket"

#: Default served model, matching the pinned Pipecat client's own default.
#: Only used when a row leaves ``code`` empty. Later Pipecat releases default
#: to ``sonic-3.6``; this tracks the version actually installed, since a model
#: the client was never tested against is not a better guess than the one it
#: ships with. An organization that wants a newer model names it in the row.
DEFAULT_TTS_MODEL: Final[str] = "sonic-3.5"

#: Speed multipliers Cartesia accepts. Outside this it rejects the request,
#: which on a call is silence; clamping and saying so is the kinder failure.
SPEED_RANGE: Final[tuple[float, float]] = (0.6, 1.5)

#: Volume multipliers Cartesia accepts.
VOLUME_RANGE: Final[tuple[float, float]] = (0.5, 2.0)

_EMOTIONS: Final[frozenset[str]] = frozenset(e.value for e in CartesiaEmotion)


def cartesia_language(code: str | None) -> str:
    """Map a call's language code to the one Cartesia takes.

    Cartesia speaks two-letter codes, so a regional tag (``pt-BR``) resolves to
    its base subtag. An unknown code is passed through rather than replaced with
    a default: a wrong language is audible and fixable, a silently English call
    is neither.

    Args:
        code: The call's language code, or ``None``.

    Returns:
        A Cartesia language code.
    """
    if not code or not code.strip():
        return "en"
    normalised = code.strip().replace("_", "-")
    base = normalised.split("-")[0].lower()
    try:
        Language(base)
    except ValueError:
        logger.warning(
            f"cartesia tts: {code!r} is not a language Cartesia lists; sending it as is"
        )
    return base


def _clamp(value: float, bounds: tuple[float, float], what: str) -> float:
    low, high = bounds
    clamped = min(max(value, low), high)
    if clamped != value:
        logger.warning(
            f"cartesia tts: {what}={value} is outside the accepted [{low}, {high}]; "
            f"using {clamped}"
        )
    return clamped


def _generation_config(
    config: TtsConfig, options: dict[str, Any]
) -> GenerationConfig | None:
    """Fold speed, volume and emotion into Cartesia's one tuning object.

    ``instructions`` is the odd one: the column holds free text for backends
    that take a style prompt, and Cartesia has no such field — only a named
    emotion. When the text happens to name one it is used; otherwise it is
    reported as ignored, which is the only honest thing to do with it.
    """
    emotion = options.get("emotion")
    if not emotion and config.instructions:
        wanted = config.instructions.strip().lower()
        if wanted in _EMOTIONS:
            emotion = wanted
        else:
            logger.warning(
                "cartesia tts: instructions are ignored — this API takes a named emotion, "
                "not free text; set provider.options['emotion'] to one of "
                f"{sorted(_EMOTIONS)[:5]}…"
            )
    if emotion and emotion not in _EMOTIONS:
        logger.warning(
            f"cartesia tts: {emotion!r} is not a listed emotion; sending it anyway"
        )

    volume = options.get("volume")
    generation = GenerationConfig(
        speed=None
        if config.speed is None
        else _clamp(config.speed, SPEED_RANGE, "speed"),
        volume=None
        if volume is None
        else _clamp(float(volume), VOLUME_RANGE, "volume"),
        emotion=emotion,
    )
    if generation.model_dump(exclude_none=True):
        return generation
    return None


class CartesiaTTSAdapter(CartesiaTTSService, BaseTtsAdapter):
    """Cartesia Sonic over its streaming WebSocket, as one of the engine's voices."""

    #: Documented behaviour, not measured behaviour — unlike the vLLM backends,
    #: nothing here has been timed against a live account yet.
    #:
    #: ``streams_incrementally`` is the load-bearing one: it is what tells the
    #: rest of the engine that first audio does not depend on cutting the reply
    #: up, so the chunking knobs do not apply.
    #:
    #: ``sample_rate`` is the class default; the rate actually dialed is
    #: ``TtsConfig.sample_rate``, since this service synthesises at whatever it
    #: is asked for.
    capabilities: TtsCapabilities = TtsCapabilities(
        streams_incrementally=True,
        deterministic=False,
        accepts_seed=False,
        sample_rate=24000,
        max_input_chars=None,
    )

    @classmethod
    def from_config(
        cls, config: TtsConfig, chunking: ChunkingConfig
    ) -> CartesiaTTSAdapter:
        """Build a synthesiser from an organization's TTS row."""
        provider = config.model.provider
        options = provider.options
        if not provider.api_key:
            logger.warning(
                f"cartesia tts: no api_key on provider {provider.url!r}; "
                "the handshake will be rejected"
            )
        streaming = chunking.mode == ChunkingModeEnum.clause
        default = ChunkingConfig()
        tuned_for_nothing = streaming and (
            chunking.min_words != default.min_words
            or chunking.max_words != default.max_words
            or chunking.clause_cuts != default.clause_cuts
        )
        return cls(
            api_key=provider.api_key or "",
            url=websocket_url(provider.url, TTS_WS_ROUTE)
            if provider.url
            else DEFAULT_TTS_URL,
            sample_rate=config.sample_rate,
            encoding="pcm_s16le",
            container="raw",
            settings=CartesiaTTSService.Settings(
                model=config.model.code or DEFAULT_TTS_MODEL,
                voice=config.voice,
                language=cartesia_language(config.language),
                generation_config=_generation_config(config, options),
                pronunciation_dict_id=options.get("pronunciation_dict_id"),
            ),
            text_aggregation_mode=(
                TextAggregationMode.TOKEN if streaming else TextAggregationMode.SENTENCE
            ),
            max_buffer_delay_ms=options.get("max_buffer_delay_ms"),
            whole_turn=not streaming,
            inert_chunking=tuned_for_nothing,
        )

    def __init__(
        self,
        *,
        whole_turn: bool = False,
        inert_chunking: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialise the service.

        Args:
            whole_turn: Synthesise each reply in one request instead of
                streaming tokens. Costs the LLM/TTS overlap, and on a backend
                that streams there is no latency left for it to buy back — it
                is here because ``ChunkingConfig`` means the same thing for
                every synthesiser.
            inert_chunking: Whether the organization tuned clause-chunking
                values this backend will not use. Logged once, so "my chunk
                settings changed nothing" is answerable from the call's log.
            **kwargs: Passed to :class:`CartesiaTTSService`.
        """
        super().__init__(**kwargs)
        if whole_turn:
            # Same swap, and the same reason, as the other synthesiser: Pipecat
            # fixes an aggregator in its constructor and exposes no setter.
            self._text_aggregator = WholeTurnAggregator(
                aggregation_type=self._text_aggregation_mode
            )
            logger.info(
                "TTS chunking off: each reply is synthesised in one request, so first audio "
                "waits for the whole reply to be generated — on a streaming backend this only "
                "costs latency"
            )
        if inert_chunking:
            logger.info(
                "cartesia tts streams incrementally: min_words/max_words/clause_cuts do not "
                "apply, the server decides when to start speaking (see max_buffer_delay_ms)"
            )

    async def _update_settings(self, delta: TTSSettings) -> dict[str, Any]:
        """Normalise the language before the vendor client stores it.

        The language switcher speaks the engine's codes — lowercase, sometimes
        regional (``pt-br``) — and Pipecat only maps the tags its ``Language``
        enum recognises verbatim, which that is not. Left alone, a mid-call
        switch would hand the server a language it does not know, in the one
        moment the call is already being disturbed.

        Args:
            delta: The settings delta, as the switcher sent it.

        Returns:
            The changed fields and their previous values.
        """
        if is_given(delta.language) and isinstance(delta.language, str):
            delta.language = cartesia_language(delta.language)
        return await super()._update_settings(delta)


TtsAdapters[TtsAdapterEnum.cartesia] = CartesiaTTSAdapter
