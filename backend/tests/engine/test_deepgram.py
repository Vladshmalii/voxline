"""The Deepgram adapters, without an account or a socket.

Same scope as the Cartesia tests: the seam between an organization's rows and
the vendor client. The results messages are built as the real SDK types, so a
schema change in the vendor package fails here rather than on a call.
"""

from __future__ import annotations

import pytest
from deepgram.listen.v1.types import ListenV1Results
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.tts_service import TextAggregationMode

from src.application.engine.audio import ASR_SAMPLE_RATE, AudioPath
from src.application.engine.chunking import WholeTurnAggregator
from src.application.engine.config import (
    ChunkingConfig,
    ModelConfig,
    ProviderConfig,
    SttConfig,
    TtsConfig,
)
from src.common.enums.engine import ChunkingModeEnum, SttAdapterEnum, TtsAdapterEnum
from src.integrations.stt.base import SttAdapters
from src.integrations.stt.deepgram import DeepgramSTTAdapter
from src.integrations.tts.base import TtsAdapters, build_tts
from src.integrations.tts.deepgram import DeepgramTTSAdapter, voice_language


def stt_config(url: str = "https://api.deepgram.com", **options) -> SttConfig:
    return SttConfig(
        adapter=SttAdapterEnum.deepgram,
        model=ModelConfig(
            code="nova-3-general",
            provider=ProviderConfig(url=url, api_key="test-key", options=options),
        ),
        language="ru",
    )


def tts_config(url: str = "https://api.deepgram.com", **overrides) -> TtsConfig:
    defaults: dict = {
        "adapter": TtsAdapterEnum.deepgram,
        "model": ModelConfig(
            code="aura-2",
            provider=ProviderConfig(url=url, api_key="test-key"),
        ),
        "voice": "aura-2-helena-en",
        "language": "en",
        "sample_rate": 16000,
    }
    defaults.update(overrides)
    return TtsConfig(**defaults)


class _Sink(DeepgramSTTService):
    """Ends the frame's journey here instead of in a pipeline."""

    frames: list

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM) -> None:
        self.frames.append(frame)


class RecordingAdapter(DeepgramSTTAdapter, _Sink):
    """The adapter under test, with the vendor's push replaced by a list.

    The sink sits *above* the adapter in the MRO rather than replacing its
    ``push_frame``, so the adapter's own transform — the language tagging —
    is exercised, which is the point of the tests below.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.frames = []


def build_stt_adapter(**options) -> tuple[RecordingAdapter, list]:
    service = RecordingAdapter.from_config(
        stt_config(**options), call_id="test", audio_path=AudioPath()
    )
    return service, service.frames


def results(transcript: str, *, is_final: bool, languages: list[str] | None = None):
    """One Results message, in the shape the SDK actually delivers."""
    alternative: dict = {"transcript": transcript, "confidence": 0.9, "words": []}
    if languages:
        alternative["languages"] = languages
    return ListenV1Results.model_validate(
        {
            "type": "Results",
            "channel_index": [0, 1],
            "duration": 1.0,
            "start": 0.0,
            "is_final": is_final,
            "speech_final": is_final,
            "channel": {"alternatives": [alternative]},
            "metadata": {
                "request_id": "r",
                "model_uuid": "u",
                "model_info": {"name": "nova-3", "version": "1", "arch": "nova-3"},
            },
        }
    )


class FakeConnection:
    """Just enough connection for ``run_stt`` to hand bytes to."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send_media(self, payload: bytes) -> None:
        self.sent.append(payload)


# -- provider rows ---------------------------------------------------------


def test_the_readiness_probe_and_the_client_agree_on_the_recogniser_route():
    assert stt_config().websocket_url() == "wss://api.deepgram.com/v1/listen"


def test_the_row_s_params_reach_the_vendor_client():
    """Deepgram adds query parameters faster than this repo would add columns."""
    service, _ = build_stt_adapter(
        params={"utterance_end_ms": 1000, "smart_format": True, "mip_opt_out": True}
    )

    assert service._settings.utterance_end_ms == 1000
    assert service._settings.smart_format is True
    # Anything the client does not declare still travels, as a query parameter.
    assert service._settings.extra == {"mip_opt_out": True}


def test_the_synthesiser_takes_the_base_url_and_appends_its_own_route():
    assert (
        build_tts(tts_config(), ChunkingConfig())._base_url == "wss://api.deepgram.com"
    )
    assert (
        build_tts(tts_config("https://gw.example.com/dg"), ChunkingConfig())._base_url
        == "wss://gw.example.com/dg"
    )


# -- transcripts -----------------------------------------------------------


async def test_finals_accumulate_and_flush_answers_the_turn_controller():
    service, _ = build_stt_adapter()

    await service._on_message(results("Здравствуйте", is_final=True))
    await service._on_message(results(", я вас слушаю", is_final=False))

    assert service.flush() == "Здравствуйте , я вас слушаю"
    assert service.flush() == ""


async def test_a_detected_language_is_read_not_assumed():
    service, _ = build_stt_adapter()
    assert service.detected_language is None

    await service._on_message(results("привет", is_final=True, languages=["ru"]))

    assert service.detected_language == "ru"


async def test_a_code_the_client_cannot_parse_does_not_cost_the_transcript():
    """``multi`` is what the multilingual model reports, and Pipecat's handler
    turns codes into a Language enum unguarded — unhandled, the ValueError
    takes the whole result down and the caller is heard as silence."""
    service, frames = build_stt_adapter()

    await service._on_message(results("привет", is_final=True, languages=["multi"]))

    assert [f.text for f in frames if isinstance(f, TranscriptionFrame)] == ["привет"]
    assert service.detected_language == "multi"
    assert service.flush() == "привет"


async def test_an_untagged_transcript_leaves_with_the_call_s_language():
    """Deepgram labels a result only when the model detects language."""
    service, frames = build_stt_adapter()

    await service._on_message(results("да", is_final=True))
    await service._on_message(results("да", is_final=False))

    finals = [f for f in frames if isinstance(f, TranscriptionFrame)]
    interims = [f for f in frames if isinstance(f, InterimTranscriptionFrame)]
    assert finals and str(finals[-1].language) == "ru"
    assert interims and str(interims[-1].language) == "ru"


async def test_telephony_audio_is_converted_to_the_rate_the_session_announced():
    service, _ = build_stt_adapter()
    connection = FakeConnection()
    service._connection = connection
    service._transport_sample_rate = 8000

    for _ in range(2):
        async for _ in service.run_stt(b"\x00\x01" * 800):  # 100ms at 8 kHz
            pass

    assert service._init_sample_rate == ASR_SAMPLE_RATE
    # One send, not two: the resampler primes its filter on the first frame.
    assert len(connection.sent) == 1
    assert len(connection.sent[0]) == pytest.approx(3200, abs=200)  # 100ms at 16 kHz


# -- the voice is the whole configuration ---------------------------------


@pytest.mark.parametrize(
    ("voice", "expected"),
    [("aura-2-helena-en", "en"), ("aura-2-celeste-es", "es"), ("custom-voice", None)],
)
def test_an_aura_voice_name_carries_its_language(voice, expected):
    assert voice_language(voice) == expected


def test_the_voice_is_sent_as_the_model_because_deepgram_has_one_name_for_both():
    service = build_tts(tts_config(voice="aura-2-thalia-en"), ChunkingConfig())

    assert service._settings.voice == "aura-2-thalia-en"
    assert service._settings.model == "aura-2-thalia-en"


def test_a_row_with_no_voice_falls_back_to_the_model_code():
    service = build_tts(
        tts_config(
            voice="",
            model=ModelConfig(
                code="aura-2-andromeda-en",
                provider=ProviderConfig(url="https://api.deepgram.com", api_key="k"),
            ),
        ),
        ChunkingConfig(),
    )

    assert service._settings.voice == "aura-2-andromeda-en"


# -- chunking --------------------------------------------------------------


def test_clause_chunking_becomes_token_streaming():
    service = build_tts(tts_config(), ChunkingConfig(mode=ChunkingModeEnum.clause))

    assert service._text_aggregation_mode == TextAggregationMode.TOKEN
    assert not isinstance(service._text_aggregator, WholeTurnAggregator)


def test_whole_turn_still_means_one_request_per_reply():
    service = build_tts(tts_config(), ChunkingConfig(mode=ChunkingModeEnum.whole_turn))

    assert isinstance(service._text_aggregator, WholeTurnAggregator)


# -- the registry ----------------------------------------------------------


def test_both_kinds_are_resolvable_by_name():
    assert SttAdapters[SttAdapterEnum.deepgram] is DeepgramSTTAdapter
    assert TtsAdapters[TtsAdapterEnum.deepgram] is DeepgramTTSAdapter


def test_the_recogniser_declares_its_own_assumptions():
    """Its endpointing is not this engine's turn boundary, and that is a claim."""
    assert any("endpointing" in a for a in DeepgramSTTAdapter.protocol_assumptions)
    assert DeepgramSTTAdapter.capabilities.server_turn_detection is False
    assert DeepgramTTSAdapter.capabilities.streams_incrementally is True
