"""The Cartesia adapters, without an account or a socket.

Everything here is about the seam between an organization's rows and a vendor
client: what a provider URL resolves to, what the call's language turns into,
what the turn controller reads at commit. The wire protocol itself is Pipecat's
and is not retested.
"""

from __future__ import annotations

import pytest
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TextAggregationMode
from websockets.protocol import State

from src.application.engine.audio import ASR_SAMPLE_RATE, AudioPath
from src.application.engine.chunking import WholeTurnAggregator
from src.application.engine.config import (
    CallContext,
    ChunkingConfig,
    ModelConfig,
    ProviderConfig,
    SttConfig,
    TtsConfig,
    resolve_profile,
)
from src.common.enums.engine import ChunkingModeEnum, SttAdapterEnum, TtsAdapterEnum
from src.integrations.stt.base import SttAdapters, build_stt
from src.integrations.stt.cartesia import CartesiaSTTAdapter, stt_base_url
from src.integrations.tts.base import TtsAdapters, build_tts
from src.integrations.tts.cartesia import CartesiaTTSAdapter, cartesia_language
from tests.engine.conftest import make_agent


def stt_config(url: str = "https://api.cartesia.ai", **overrides) -> SttConfig:
    defaults: dict = {
        "adapter": SttAdapterEnum.cartesia,
        "model": ModelConfig(
            code="ink-whisper",
            provider=ProviderConfig(url=url, api_key="test-key"),
        ),
        "language": "ru",
    }
    defaults.update(overrides)
    return SttConfig(**defaults)


def tts_config(url: str = "https://api.cartesia.ai", **overrides) -> TtsConfig:
    defaults: dict = {
        "adapter": TtsAdapterEnum.cartesia,
        "model": ModelConfig(
            code="sonic-3.5",
            provider=ProviderConfig(url=url, api_key="test-key"),
        ),
        "voice": "00000000-0000-0000-0000-000000000000",
        "language": "ru",
        "sample_rate": 16000,
    }
    defaults.update(overrides)
    return TtsConfig(**defaults)


def build_stt_adapter(**overrides) -> tuple[CartesiaSTTAdapter, list]:
    service = build_stt(stt_config(**overrides), call_id="test", audio_path=AudioPath())
    frames: list = []

    async def collect(frame, direction=None):
        frames.append(frame)

    service.push_frame = collect  # type: ignore[method-assign]
    return service, frames


class FakeWebsocket:
    """Just enough socket for ``run_stt`` to hand bytes to."""

    state = State.OPEN

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send(self, payload: bytes) -> None:
        self.sent.append(payload)


# -- provider rows to vendor endpoints ------------------------------------


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ("https://api.cartesia.ai", "api.cartesia.ai"),
        ("api.cartesia.ai", "api.cartesia.ai"),
        ("https://gw.example.com/cartesia/", "gw.example.com/cartesia"),
        ("wss://gw.example.com:8443/cartesia", "gw.example.com:8443/cartesia"),
        ("", "api.cartesia.ai"),
    ],
)
def test_a_provider_row_resolves_to_the_host_the_vendor_client_wants(row, expected):
    """Pipecat's client builds the route itself, so it is handed a host, not a URL."""
    assert stt_base_url(row) == expected


def test_the_readiness_probe_and_the_client_agree_on_the_recogniser_route():
    """A probe that dials a different URI than the call is worse than no probe."""
    config = stt_config()
    assert config.websocket_url() == "wss://api.cartesia.ai/stt/websocket"
    assert stt_base_url(config.model.provider.url) in config.websocket_url()


async def test_the_recogniser_url_keeps_a_reverse_proxy_prefix():
    service, _ = build_stt_adapter(url="https://gw.example.com/cartesia")
    dialed: list[str] = []

    async def connect(uri, **_kwargs):
        dialed.append(uri)
        return FakeWebsocket()

    service._websocket_connect = connect  # type: ignore[method-assign]
    await service._connect_websocket()
    assert dialed[0].startswith("wss://gw.example.com/cartesia/stt/websocket?")


def test_the_synthesiser_url_keeps_a_reverse_proxy_prefix():
    service = build_tts(tts_config("https://gw.example.com/cartesia"), ChunkingConfig())
    assert service._url == "wss://gw.example.com/cartesia/tts/websocket"


def test_a_pinned_websocket_url_is_used_verbatim():
    """An operator who pasted the full URI knows their layout better than a default."""
    service = build_tts(tts_config("wss://gw.example.com/custom/tts"), ChunkingConfig())
    assert service._url == "wss://gw.example.com/custom/tts"


# -- the call's language ---------------------------------------------------


def test_the_call_language_reaches_both_vendor_clients():
    """Without this the first turn runs on the vendor's default language."""
    agent = make_agent(
        stt=stt_config(),
        tts=tts_config(language=None),
        default_language="ru",
    )
    profile = resolve_profile(agent, CallContext(call_id="c", org_uuid="o"))

    assert profile.tts.language == "ru"
    assert build_tts(profile.tts, ChunkingConfig())._settings.language == "ru"
    service, _ = build_stt_adapter()
    assert service._settings.language == "ru"


@pytest.mark.parametrize(
    ("code", "expected"), [("ru", "ru"), ("pt-BR", "pt"), ("en_US", "en"), (None, "en")]
)
def test_regional_tags_resolve_to_the_two_letter_code_cartesia_speaks(code, expected):
    assert cartesia_language(code) == expected


async def test_a_mid_call_switch_normalises_the_language_too():
    """The switcher speaks the engine's codes; the server does not."""
    service = build_tts(tts_config(), ChunkingConfig())

    await service._update_settings(TTSSettings(language="pt-br"))

    assert service._settings.language == "pt"


# -- transcripts -----------------------------------------------------------


async def test_finals_accumulate_and_flush_answers_the_turn_controller():
    """flush() is local bookkeeping: at commit there is no time for a round trip."""
    service, _ = build_stt_adapter()

    await service._on_transcript({"text": "Здравствуйте", "is_final": True})
    await service._on_transcript({"text": ", я вас слушаю", "is_final": False})

    assert service.flush() == "Здравствуйте , я вас слушаю"
    assert service.flush() == ""


async def test_a_reported_language_is_read_not_assumed():
    service, _ = build_stt_adapter()
    assert service.detected_language is None

    await service._on_transcript({"text": "hello", "is_final": True, "language": "EN"})

    assert service.detected_language == "en"


async def test_a_transcript_with_no_language_is_tagged_with_the_call_s():
    """Some model and account combinations never report one."""
    service, frames = build_stt_adapter()

    await service._on_transcript({"text": "привет", "is_final": False})

    interims = [f for f in frames if isinstance(f, InterimTranscriptionFrame)]
    assert interims and str(interims[-1].language) == "ru"
    assert service.detected_language is None


async def test_finals_reach_the_pipeline_as_final_frames():
    service, frames = build_stt_adapter()

    await service._on_transcript({"text": "да", "is_final": True})

    assert [f.text for f in frames if isinstance(f, TranscriptionFrame)] == ["да"]


async def test_telephony_audio_is_converted_to_the_rate_the_session_announced():
    """The query string says 16 kHz; the transport may be an 8 kHz phone leg."""
    service, _ = build_stt_adapter()
    socket = FakeWebsocket()
    service._websocket = socket
    service._transport_sample_rate = 8000

    for _ in range(2):
        async for _ in service.run_stt(b"\x00\x01" * 800):  # 100ms at 8 kHz
            pass

    # Pinned at construction, not taken from the pipeline: it is what the
    # session's query string announces.
    assert service._init_sample_rate == ASR_SAMPLE_RATE
    # One send, not two: the resampler primes its filter on the first frame and
    # returns nothing, and an empty frame is not sent.
    assert len(socket.sent) == 1
    assert len(socket.sent[0]) == pytest.approx(3200, abs=200)  # 100ms at 16 kHz


# -- chunking --------------------------------------------------------------


def test_clause_chunking_becomes_token_streaming():
    """This backend streams, so cutting the reply up client-side buys nothing."""
    service = build_tts(tts_config(), ChunkingConfig(mode=ChunkingModeEnum.clause))

    assert service._text_aggregation_mode == TextAggregationMode.TOKEN
    assert not isinstance(service._text_aggregator, WholeTurnAggregator)


def test_whole_turn_still_means_one_request_per_reply():
    """The knob means the same thing on every synthesiser, streaming or not."""
    service = build_tts(tts_config(), ChunkingConfig(mode=ChunkingModeEnum.whole_turn))

    assert isinstance(service._text_aggregator, WholeTurnAggregator)


# -- the vendor's tuning object -------------------------------------------


def test_a_speed_outside_the_accepted_range_is_clamped_not_sent():
    """Cartesia rejects it, and a rejected request is silence on a live call."""
    service = build_tts(tts_config(speed=2.0), ChunkingConfig())

    assert service._settings.generation_config.speed == 1.5


def test_instructions_are_used_when_they_name_an_emotion():
    """The column holds free text; this API only takes a named emotion."""
    service = build_tts(tts_config(instructions="Calm"), ChunkingConfig())

    assert service._settings.generation_config.emotion == "calm"


def test_free_text_instructions_are_dropped_rather_than_sent():
    service = build_tts(
        tts_config(instructions="speak warmly, like a friend"), ChunkingConfig()
    )

    assert service._settings.generation_config is None


def test_options_carry_what_has_no_column():
    config = tts_config()
    config.model.provider.options.update(
        {
            "emotion": "confident",
            "volume": 1.5,
            "pronunciation_dict_id": "dict-1",
            "max_buffer_delay_ms": 120,
        }
    )

    service = build_tts(config, ChunkingConfig())

    assert service._settings.generation_config.emotion == "confident"
    assert service._settings.generation_config.volume == 1.5
    assert service._settings.pronunciation_dict_id == "dict-1"
    assert service._max_buffer_delay_ms == 120


# -- the registry ----------------------------------------------------------


def test_both_kinds_are_resolvable_by_name():
    """Adding a provider is an enum value, an adapter and a row — nothing else."""
    assert SttAdapters[SttAdapterEnum.cartesia] is CartesiaSTTAdapter
    assert TtsAdapters[TtsAdapterEnum.cartesia] is CartesiaTTSAdapter


def test_the_recogniser_declares_its_own_assumptions():
    """Logged per call from the backend actually selected."""
    assert any("wss" in a for a in CartesiaSTTAdapter.protocol_assumptions)
    assert CartesiaSTTAdapter.capabilities.min_commit_seconds == 0.0
    assert CartesiaTTSAdapter.capabilities.streams_incrementally is True
