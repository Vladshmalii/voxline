"""Voxtral's dialect of the realtime protocol. No network.

The Qwen client drops every Voxtral delta on the floor — no ``<asr_text>``
marker means no text, and no trailing newline means no final — so these tests
pin the two behaviours that difference costs.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame

from src.application.engine.audio import AudioPath
from src.integrations.stt.qwen3_asr import Qwen3ASRService
from src.integrations.stt.voxtral import VoxtralRealtimeService

VOXTRAL_DELTAS = [" Здравствуйте", ",", "", " меня", " зовут", "", " Андрей"]
EXPECTED = "Здравствуйте, меня зовут Андрей"


def build(**kwargs) -> tuple[VoxtralRealtimeService, list]:
    frames: list = []
    service = VoxtralRealtimeService(
        ws_url="ws://127.0.0.1:59101/v1/realtime",
        model="mistralai/Voxtral-Mini-4B-Realtime-2602",
        language="ru",
        session_id="test",
        audio_path=AudioPath(),
        **kwargs,
    )

    async def collect(frame, direction=None):
        frames.append(frame)

    service.push_frame = collect  # type: ignore[method-assign]
    return service, frames


async def feed(service: VoxtralRealtimeService, deltas=VOXTRAL_DELTAS) -> None:
    for delta in deltas:
        await service._handle_delta(delta)


async def test_deltas_without_a_preamble_still_produce_text():
    """The Qwen client requires `<asr_text>`; Voxtral never sends one."""
    _service, frames = await _fed()

    interims = [f for f in frames if isinstance(f, InterimTranscriptionFrame)]
    assert interims, "no partials — the delta stream was parsed as empty"
    assert interims[-1].text == EXPECTED


async def test_the_language_is_the_call_s_not_the_server_s_guess():
    service, frames = await _fed()

    assert service.detected_language is None
    assert frames[-1].language == "ru"


async def test_quiet_after_the_last_delta_finalises_the_utterance():
    """There is no terminator and no completion event, so silence is the signal."""
    _service, frames = await _fed(finalize_after_ms=60)
    assert not [f for f in frames if isinstance(f, TranscriptionFrame)]

    await asyncio.sleep(0.12)

    finals = [f for f in frames if isinstance(f, TranscriptionFrame)]
    assert len(finals) == 1
    assert finals[0].text == EXPECTED
    assert finals[0].finalized is True


async def test_a_late_delta_postpones_the_final():
    """A gap inside the burst must not cut the utterance in half."""
    service, frames = await _fed(finalize_after_ms=120)

    await asyncio.sleep(0.06)
    await service._handle_delta(", я вас слушаю")
    await asyncio.sleep(0.06)
    assert not [f for f in frames if isinstance(f, TranscriptionFrame)]

    await asyncio.sleep(0.12)
    finals = [f for f in frames if isinstance(f, TranscriptionFrame)]
    assert len(finals) == 1
    assert finals[0].text.endswith("я вас слушаю")


async def test_flush_returns_the_turn_text_before_the_timer_fires():
    """The turn controller reads flush() at commit; it cannot wait on a timer."""
    service, _ = await _fed(finalize_after_ms=5000)

    assert service.flush() == EXPECTED


async def test_the_backend_declares_its_own_protocol_assumptions():
    """bot.py logs these per call, so they must not be the Qwen ones."""
    assert (
        VoxtralRealtimeService.protocol_assumptions
        != Qwen3ASRService.protocol_assumptions
    )
    assert any("silence" in a for a in VoxtralRealtimeService.protocol_assumptions)


async def _fed(**kwargs):
    service, frames = build(**kwargs)
    await feed(service)
    return service, frames


@pytest.fixture(autouse=True)
async def _cancel_pending_timers():
    """Leave no finalize timer running into the next test."""
    yield
    for task in asyncio.all_tasks():
        if (
            task is not asyncio.current_task()
            and task.get_coro().__name__ == "_finalize_when_quiet"
        ):
            task.cancel()


def test_realtime_clients_carry_the_websocket_machinery():
    """BaseSttAdapter is a plain STTService by design; the realtime clients
    need pipecat's websocket mixin on top. Without it the first StartFrame
    dies on `'super' object has no attribute '_connect'`, the socket never
    opens, and the call runs deaf — greeting works, every reply is silence."""
    from pipecat.services.stt_service import WebsocketSTTService

    service, _ = build()

    assert isinstance(service, WebsocketSTTService)
    assert service._websocket is None
