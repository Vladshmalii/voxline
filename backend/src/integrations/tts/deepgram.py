"""Deepgram Aura TTS: a streaming voice with no knobs to speak of.

The plainest synthesiser in the package, and the mapping onto ``TtsConfig``
says most of what there is to know:

    voice         → ``model=`` on the socket. Deepgram has no separate model
                    and voice: ``aura-2-helena-en`` *is* both, and the language
                    is the suffix of that name.
    sample_rate   → ``sample_rate=``, raw ``linear16`` PCM out.
    language      → nothing. The voice carries it, and a mid-call switch works
                    because the switcher changes the voice too. The vendor
                    client's settings object does accept a language, which is
                    misleading: in the pinned release the socket's query string
                    carries only model, encoding, sample rate and mip_opt_out,
                    so the value goes nowhere.
    speed         → nothing. This API has no speaking-rate parameter.
    instructions  → nothing. No style prompt either.

The last two are the reason this module logs rather than stays silent: a row
that sets ``speed=0.9`` on Deepgram gets the same voice it would have got
anyway, and an operator should learn that from a log line rather than from
listening to twenty calls.

Chunking behaves as on the other streaming backend — ``clause`` streams tokens
and lets the server decide when to speak, ``whole_turn`` synthesises the reply
in one request. Nothing here has been measured against a live account.
"""

from __future__ import annotations

from typing import Any, Final

from loguru import logger
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.tts_service import TextAggregationMode

from src.application.engine.capabilities import TtsCapabilities
from src.application.engine.chunking import WholeTurnAggregator
from src.application.engine.config import ChunkingConfig, TtsConfig
from src.common.enums.engine import ChunkingModeEnum, TtsAdapterEnum
from src.integrations.tts.base import BaseTtsAdapter, TtsAdapters
from src.utils.url import websocket_url

#: Where Deepgram's synthesiser lives when a provider row leaves the URL empty.
DEFAULT_TTS_URL: Final[str] = "wss://api.deepgram.com"

#: Voice used when a row leaves it empty. Named for what it is: an English one.
DEFAULT_VOICE: Final[str] = "aura-2-helena-en"


def voice_language(voice: str) -> str | None:
    """The language an Aura voice name ends in, if it ends in one.

    ``aura-2-helena-en`` → ``"en"``. Returns ``None`` for a name that does not
    follow the convention, since a guess is worse than no check.

    Args:
        voice: The voice id from the row.

    Returns:
        A lowercase language code, or ``None``.
    """
    tail = voice.strip().lower().rsplit("-", 1)[-1]
    return tail if len(tail) == 2 and tail.isalpha() else None


class DeepgramTTSAdapter(DeepgramTTSService, BaseTtsAdapter):
    """Deepgram Aura over its streaming WebSocket."""

    #: Documented behaviour, not measured behaviour.
    #:
    #: ``deterministic`` is left false because it has not been checked, not
    #: because drift was observed — it costs nothing here (this backend streams,
    #: so nothing in the engine is compensating for redraws) and claiming
    #: determinism that was never verified would.
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
    ) -> DeepgramTTSAdapter:
        """Build a synthesiser from an organization's TTS row."""
        provider = config.model.provider
        if not provider.api_key:
            logger.warning(
                f"deepgram tts: no api_key on provider {provider.url!r}; "
                "the handshake will be rejected"
            )

        # The row binds a model and a voice separately, as every other backend
        # needs; Deepgram has one name for both. The voice wins, because that
        # is the field a language row overrides.
        voice = config.voice or config.model.code or DEFAULT_VOICE
        spoken = voice_language(voice)
        if (
            spoken
            and config.language
            and spoken != config.language.split("-")[0].lower()
        ):
            logger.warning(
                f"deepgram tts: voice {voice!r} speaks {spoken!r} but the call runs in "
                f"{config.language!r}; Deepgram has no language parameter, so the voice is "
                "the only thing that decides"
            )
        inert = [
            name
            for name, value in (
                ("speed", config.speed),
                ("instructions", config.instructions),
            )
            if value is not None
        ]
        if inert:
            logger.info(
                f"deepgram tts: {', '.join(inert)} set on the row but this API has no such "
                "parameter; the voice is the whole configuration"
            )

        streaming = chunking.mode == ChunkingModeEnum.clause
        return cls(
            api_key=provider.api_key or "",
            base_url=websocket_url(provider.url) if provider.url else DEFAULT_TTS_URL,
            sample_rate=config.sample_rate,
            encoding="linear16",
            settings=DeepgramTTSService.Settings(voice=voice, model=voice),
            text_aggregation_mode=(
                TextAggregationMode.TOKEN if streaming else TextAggregationMode.SENTENCE
            ),
            whole_turn=not streaming,
            **provider.options.get("client", {}),
        )

    def __init__(self, *, whole_turn: bool = False, **kwargs: Any) -> None:
        """Initialise the service.

        Args:
            whole_turn: Synthesise each reply in one request instead of
                streaming tokens. Means the same thing it means on every other
                synthesiser; on a streaming backend it only costs latency.
            **kwargs: Passed to :class:`DeepgramTTSService`.
        """
        super().__init__(**kwargs)
        if whole_turn:
            # Pipecat fixes an aggregator in its constructor and exposes no
            # setter, so it is swapped afterwards — as in every adapter here.
            self._text_aggregator = WholeTurnAggregator(
                aggregation_type=self._text_aggregation_mode
            )
            logger.info(
                "TTS chunking off: each reply is synthesised in one request, so first audio "
                "waits for the whole reply to be generated"
            )


TtsAdapters[TtsAdapterEnum.deepgram] = DeepgramTTSAdapter
