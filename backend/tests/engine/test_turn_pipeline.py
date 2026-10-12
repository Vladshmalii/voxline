"""Turn decisions through Pipecat's real queues, context writes and watchdog.

Provider calls and acoustic inference are faked; the user aggregator and turn
controller are production objects. Inspect before EndFrame, which itself flushes
aggregation and could otherwise hide a lost/stalled turn.
"""

import time

import pytest
from pipecat.frames.frames import (
    EndFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    STTMetadataFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from src.application.engine.context.user import CallUserAggregator
from src.application.engine.turn.controller import CascadingTurnStopStrategy
from tests.engine.conftest import make_profile
from tests.engine.test_turn_controller import FakeTurnAnalyzer


class InputClock(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(
            frame, (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
        ):
            frame.timestamp = time.time()
        await self.push_frame(frame, direction)


class Requests(FrameProcessor):
    def __init__(self):
        super().__init__(enable_direct_mode=True)
        self.requests = []
        self.prompts = []
        self.starts = 0
        self.interruptions = 0
        self.ended = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and not self.ended:
            if isinstance(frame, EndFrame):
                self.ended = True
            elif isinstance(frame, LLMContextFrame):
                self.requests.append([dict(m) for m in frame.context.messages])
            elif isinstance(frame, TTSSpeakFrame):
                self.prompts.append(frame.text)
            elif isinstance(frame, UserStartedSpeakingFrame):
                self.starts += 1
            elif isinstance(frame, InterruptionFrame):
                self.interruptions += 1
        await self.push_frame(frame, direction)


async def exercise(frames, *, smart_turn=False, timeout_ms=240):
    context = LLMContext([])
    strategy = CascadingTurnStopStrategy(
        turn_analyzer=FakeTurnAnalyzer() if smart_turn else None,
        profile=make_profile(
            smart_turn=smart_turn,
            min_delay_ms=10,
            max_delay_ms=60,
            repoll_ms=10,
            silence_fallback_ms=40,
            transcript_timeout_ms=timeout_ms,
        ),
    )
    user = CallUserAggregator(
        context,
        params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(stop=[strategy]),
            # Keep the actual 5s watchdog: none of these turns may depend on it.
        ),
    )
    requests = Requests()
    snapshots = []

    @user.event_handler("on_user_turn_message_added")
    async def on_message(_, message):
        snapshots.append(message.content)

    class EndSnapshot(InputClock):
        async def process_frame(self, frame, direction):
            if isinstance(frame, EndFrame):
                requests.ended = True
            await super().process_frame(frame, direction)

    await run_test(
        Pipeline([EndSnapshot(), user, requests]),
        frames_to_send=[
            STTMetadataFrame(service_name="test", ttfs_p99_latency=0.1),
            *frames,
        ],
    )
    return requests, context, snapshots


def final(text, *, finalized=True):
    return TranscriptionFrame(text, "user", "ts", finalized=finalized)


def interim(text):
    return InterimTranscriptionFrame(text, "user", "ts")


def start():
    return VADUserStartedSpeakingFrame(start_secs=0)


def stop():
    return VADUserStoppedSpeakingFrame(stop_secs=0)


async def test_normal_turn_still_runs_once_and_preserves_public_transcript_event():
    got, _, messages = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final("where is my order"),
            SleepFrame(0.02),
            stop(),
            SleepFrame(0.1),
        ]
    )
    assert got.requests == [[{"role": "user", "content": "where is my order"}]]
    assert messages == ["where is my order"]
    assert got.starts == got.interruptions == 1
    assert not got.prompts


async def test_late_final_runs_in_original_turn_before_watchdog():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            interim("where is my order"),
            SleepFrame(0.02),
            stop(),
            SleepFrame(0.13),
            final("where is my order"),
            SleepFrame(0.05),
        ]
    )
    assert got.requests == [[{"role": "user", "content": "where is my order"}]]
    assert got.starts == got.interruptions == 1
    assert not got.prompts


async def test_multiple_final_segments_and_pending_interim_are_not_cut_short():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final("please check", finalized=False),
            interim("my order"),
            SleepFrame(0.02),
            stop(),
            SleepFrame(0.13),
            final("my order status"),
            SleepFrame(0.05),
        ]
    )
    assert got.requests == [
        [{"role": "user", "content": "please check my order status"}]
    ]
    assert got.starts == 1
    assert not got.prompts


async def test_new_interim_invalidates_an_earlier_finalized_segment():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final("please check"),
            interim("my order"),
            SleepFrame(0.02),
            stop(),
            SleepFrame(0.13),
            final("my order status"),
            SleepFrame(0.05),
        ]
    )
    assert got.requests == [
        [{"role": "user", "content": "please check my order status"}]
    ]
    assert got.starts == 1


async def test_resumed_speech_cancels_pending_stt_commit():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            interim("please check"),
            stop(),
            SleepFrame(0.07),
            start(),
            SleepFrame(0.02),
            final("please check my order"),
            SleepFrame(0.06),
            stop(),
            SleepFrame(0.14),
        ]
    )
    assert len(got.requests) == 1
    assert got.requests[0][-1]["content"] == "please check my order"
    assert got.starts == 1
    assert not got.prompts


async def test_no_response_while_resumed_speech_is_still_active():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            interim("please check"),
            stop(),
            SleepFrame(0.07),
            start(),
            SleepFrame(0.02),
            final("please check my order"),
            SleepFrame(0.3),
        ]
    )
    assert not got.requests and not got.prompts


async def test_fragment_saves_context_and_events_without_dispatching_llm():
    got, context, messages = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final("I want to check my"),
            stop(),
            SleepFrame(0.12),
        ],
        smart_turn=True,
    )
    assert not got.requests
    assert got.prompts == ["Sorry, go ahead."]
    assert context.messages == [{"role": "user", "content": "I want to check my"}]
    assert messages == ["I want to check my"]


async def test_reprompt_does_not_suppress_the_next_complete_turn():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final("I want to check my"),
            stop(),
            SleepFrame(0.12),
            start(),
            SleepFrame(0.02),
            final("order status please"),
            stop(),
            SleepFrame(0.12),
        ],
        smart_turn=True,
    )
    assert got.prompts == ["Sorry, go ahead."]
    assert got.requests == [
        [
            {"role": "user", "content": "I want to check my"},
            {"role": "user", "content": "order status please"},
        ]
    ]


@pytest.mark.parametrize("text", ["", "where is my order"])
async def test_missing_final_has_bounded_wait_and_never_answers_an_interim(text):
    frames = [start(), SleepFrame(0.02)]
    if text:
        frames.append(interim(text))
    frames += [stop(), SleepFrame(0.3)]
    got, _, _ = await exercise(frames)
    assert not got.requests
    assert got.prompts == ["Sorry, go ahead."]


async def test_non_finalized_stt_uses_provider_deadline_and_collects_segments():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final("please check", finalized=False),
            stop(),
            SleepFrame(0.06),
            final("my order", finalized=False),
            SleepFrame(0.12),
        ]
    )
    assert got.requests == [[{"role": "user", "content": "please check my order"}]]
    assert got.starts == 1


async def test_transcript_without_vad_does_not_wait_five_seconds():
    got, _, _ = await exercise([final("hello"), SleepFrame(0.16)])
    assert got.requests == [[{"role": "user", "content": "hello"}]]
    assert got.starts == 1


async def test_shutdown_cancels_pending_transcript_timer():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            interim("hello"),
            stop(),
            SleepFrame(0.08),
        ]
    )
    assert not got.requests and not got.prompts


async def test_old_final_is_not_a_transcript_for_resumed_speech():
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final("please check"),
            stop(),
            SleepFrame(0.02),
            start(),
            SleepFrame(0.02),
            stop(),
            SleepFrame(0.3),
        ]
    )
    assert not got.requests
    assert got.prompts == ["Sorry, go ahead."]


@pytest.mark.parametrize("text", ["yes", "no", "hello"])
async def test_short_complete_answers_are_preserved(text):
    got, _, _ = await exercise(
        [
            start(),
            SleepFrame(0.02),
            final(text),
            stop(),
            SleepFrame(0.12),
        ],
        smart_turn=True,
    )
    assert got.requests == [[{"role": "user", "content": text}]]
    assert not got.prompts
