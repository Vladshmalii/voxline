"""The latency observer's per-turn payload: the summary log line, as data.

The playground renders these numbers live, so their semantics are pinned here:
``waiting_user_ms`` is floor-yield → caller speaks, ``stt_ms`` is caller
stopped → transcript committed, ``ttt_ms`` is LLM request → response complete,
``tts_ms`` is first TTS request → first audio.
"""

from __future__ import annotations

from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.observability import TurnLatencyObserver


def build_observer() -> tuple[TurnLatencyObserver, list[dict[str, Any]]]:
    observer = TurnLatencyObserver(call_id="test")
    payloads: list[dict[str, Any]] = []

    async def collect(payload: dict[str, Any]) -> None:
        payloads.append(payload)

    observer.notify = collect
    return observer, payloads


async def see(observer: TurnLatencyObserver, frame: Frame, at_ms: float) -> None:
    await observer.on_push_frame(
        FramePushed(
            source=None,  # type: ignore[arg-type] - the observer never touches them
            destination=None,  # type: ignore[arg-type]
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=int(at_ms * 1_000_000),
        )
    )


async def run_turn(observer: TurnLatencyObserver, *, offset: float = 0.0) -> None:
    """One complete caller turn with fixed, easily-asserted stage gaps."""
    await see(observer, UserStartedSpeakingFrame(), offset + 5000)
    await see(observer, VADUserStoppedSpeakingFrame(), offset + 7000)
    await see(observer, UserStoppedSpeakingFrame(), offset + 7400)
    await see(observer, LLMFullResponseStartFrame(), offset + 7500)
    await see(observer, LLMTextFrame("Здравствуйте"), offset + 8000)
    await see(observer, TTSStartedFrame(), offset + 8100)
    await see(
        observer,
        TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=16000, num_channels=1),
        offset + 9000,
    )
    await see(observer, LLMFullResponseEndFrame(), offset + 9500)
    await see(observer, BotStoppedSpeakingFrame(), offset + 15000)


async def test_a_full_turn_reports_every_stage():
    observer, payloads = build_observer()
    await see(observer, StartFrame(), 1000)

    await run_turn(observer)

    assert payloads == [
        {
            "event": "timing",
            "turn": 1,
            "waiting_user_ms": 4000,  # call start 1000 → caller speaks 5000
            "user_turn_ms": 2400,  # speaks 5000 → commit 7400
            "stt_ms": 400,  # stops 7000 → commit 7400
            "ttt_first_token_ms": 500,  # llm start 7500 → first token 8000
            "ttt_ms": 2000,  # llm start 7500 → llm end 9500
            "tts_ms": 900,  # tts request 8100 → first audio 9000
            "voice_to_voice_ms": 2000,  # stops 7000 → first audio 9000
            "interrupted": False,
        }
    ]


async def test_waiting_resumes_from_the_previous_bot_stop():
    observer, payloads = build_observer()
    await see(observer, StartFrame(), 1000)
    await run_turn(observer)  # the agent yields the floor at 15000

    await run_turn(observer, offset=15000)  # caller speaks again at 20000

    assert payloads[1]["turn"] == 2
    assert payloads[1]["waiting_user_ms"] == 5000


async def test_the_greeting_turn_has_no_user_stages():
    """greet_first runs the LLM with no caller speech before it."""
    observer, payloads = build_observer()
    await see(observer, StartFrame(), 0)

    await see(observer, LLMFullResponseStartFrame(), 100)
    await see(observer, LLMTextFrame("Здравствуйте"), 600)
    await see(observer, TTSStartedFrame(), 700)
    await see(
        observer,
        TTSAudioRawFrame(audio=b"\x00\x00", sample_rate=16000, num_channels=1),
        1500,
    )
    await see(observer, LLMFullResponseEndFrame(), 2000)
    await see(observer, BotStoppedSpeakingFrame(), 3000)

    (payload,) = payloads
    assert payload["waiting_user_ms"] is None
    assert payload["user_turn_ms"] is None
    assert payload["stt_ms"] is None
    assert payload["voice_to_voice_ms"] is None
    assert payload["ttt_ms"] == 1900
    assert payload["tts_ms"] == 800


async def test_a_turn_with_nothing_in_it_reports_nothing():
    """BotStopped after a canned prompt (no commit, no LLM) stays silent."""
    observer, payloads = build_observer()
    await see(observer, StartFrame(), 0)

    await see(observer, BotStoppedSpeakingFrame(), 4000)

    assert payloads == []


async def test_a_caller_turn_over_a_silent_agent_is_not_an_interruption():
    """Pipecat broadcasts an InterruptionFrame at every user turn start."""
    observer, payloads = build_observer()
    await see(observer, StartFrame(), 1000)

    await see(observer, UserStartedSpeakingFrame(), 5000)
    await see(observer, InterruptionFrame(), 5001)
    await see(observer, VADUserStoppedSpeakingFrame(), 7000)
    await see(observer, UserStoppedSpeakingFrame(), 7400)
    await see(observer, LLMFullResponseStartFrame(), 7500)
    await see(observer, LLMFullResponseEndFrame(), 9500)
    await see(observer, BotStoppedSpeakingFrame(), 15000)

    assert payloads[0]["interrupted"] is False


async def test_a_barge_in_reports_the_reply_it_cut_short():
    observer, payloads = build_observer()
    await see(observer, StartFrame(), 1000)
    await see(observer, UserStartedSpeakingFrame(), 5000)
    await see(observer, UserStoppedSpeakingFrame(), 7400)
    await see(observer, LLMFullResponseStartFrame(), 7500)
    await see(observer, BotStartedSpeakingFrame(), 9000)

    # The caller talks over the reply; the cleared audio stops the bot after.
    await see(observer, UserStartedSpeakingFrame(), 11000)
    await see(observer, InterruptionFrame(), 11001)
    await see(observer, BotStoppedSpeakingFrame(), 11050)
    (cut_short,) = payloads
    assert cut_short["turn"] == 1
    assert cut_short["interrupted"] is True

    await see(observer, UserStoppedSpeakingFrame(), 12000)
    await see(observer, LLMFullResponseStartFrame(), 12100)
    await see(observer, BotStoppedSpeakingFrame(), 16000)
    assert payloads[1]["turn"] == 2
    assert payloads[1]["interrupted"] is False
