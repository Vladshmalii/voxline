"""Turn controller: the delay cascade and fragment classification. No network."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

import pytest
from pipecat.audio.turn.base_turn_analyzer import BaseTurnAnalyzer, EndOfTurnState
from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.utils.asyncio.task_manager import BaseTaskManager

from src.application.engine.turn.controller import (
    CascadingTurnStopStrategy,
    Completeness,
    HeuristicFragmentClassifier,
    TurnDecision,
)
from tests.engine.conftest import make_profile

# Real-time tests, so the delays are scaled down by ~25x from production values.
MIN_DELAY_MS = 20
MAX_DELAY_MS = 140
REPOLL_MS = 30


class FakeTaskManager(BaseTaskManager):
    """Minimal task manager. The real one needs a running pipeline."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    def create_task(self, coroutine, name: str, *args, **kwargs) -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def cancel_task(
        self, task: asyncio.Task, timeout: float | None = None
    ) -> None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def current_tasks(self) -> Sequence[asyncio.Task]:
        return tuple(self._tasks)


def fake_setup() -> FrameProcessorSetup:
    """What the user turn controller hands its strategies, minus a pipeline."""
    return FrameProcessorSetup(
        clock=None, task_manager=FakeTaskManager(), pipeline_worker=None
    )


class FakeTurnAnalyzer(BaseTurnAnalyzer):
    """Smart Turn stand-in with a scripted sequence of verdicts."""

    def __init__(self, verdicts: list[EndOfTurnState] | None = None) -> None:
        super().__init__(sample_rate=16000)
        self._verdicts = verdicts or []
        self.poll_times: list[float] = []
        self.cleared = 0

    @property
    def speech_triggered(self) -> bool:
        return True

    @property
    def params(self):
        return None

    def append_audio(self, buffer: bytes, is_speech: bool) -> EndOfTurnState:
        return EndOfTurnState.INCOMPLETE

    async def analyze_end_of_turn(self):
        self.poll_times.append(time.time())
        index = len(self.poll_times) - 1
        if index < len(self._verdicts):
            return self._verdicts[index], None
        return EndOfTurnState.INCOMPLETE, None

    def update_vad_start_secs(self, vad_start_secs: float) -> None:
        pass

    def clear(self) -> None:
        self.cleared += 1

    async def cleanup(self) -> None:
        pass


class Harness:
    """Drives a strategy and records what it emitted."""

    def __init__(
        self, strategy: CascadingTurnStopStrategy, analyzer: FakeTurnAnalyzer
    ) -> None:
        self.strategy = strategy
        self.analyzer = analyzer
        self.inference_triggered = 0
        self.turn_stopped = 0
        self.committed_at: float | None = None
        self.pushed: list = []

        strategy.add_event_handler(
            "on_user_turn_inference_triggered", self._on_inference
        )
        strategy.add_event_handler("on_user_turn_stopped", self._on_stopped)
        strategy.add_event_handler("on_push_frame", self._on_push)

    async def _on_inference(self, _strategy) -> None:
        self.inference_triggered += 1

    async def _on_stopped(self, _strategy, _params) -> None:
        self.turn_stopped += 1
        self.committed_at = time.time()

    async def _on_push(self, _strategy, frame, _direction) -> None:
        self.pushed.append(frame)

    async def speech_stopped(self, *, stop_secs: float = 0.0) -> float:
        """Report end of speech and return the wall-clock instant it happened."""
        now = time.time()
        await self.strategy.process_frame(
            VADUserStoppedSpeakingFrame(stop_secs=stop_secs, timestamp=now)
        )
        return now - stop_secs

    async def speech_started(self) -> None:
        await self.strategy.process_frame(
            VADUserStartedSpeakingFrame(start_secs=0.0, timestamp=time.time())
        )

    async def transcript(self, text: str, *, final: bool = True) -> None:
        frame = (
            TranscriptionFrame(text, "user", "ts", finalized=True)
            if final
            else InterimTranscriptionFrame(text, "user", "ts")
        )
        await self.strategy.process_frame(frame)

    def reprompts(self) -> list[str]:
        return [f.text for f in self.pushed if isinstance(f, TTSSpeakFrame)]


async def build(
    *,
    verdicts: list[EndOfTurnState] | None = None,
    smart_turn: bool = True,
    **profile_kwargs,
) -> Harness:
    analyzer = FakeTurnAnalyzer(verdicts)
    profile = make_profile(
        smart_turn=smart_turn,
        min_delay_ms=MIN_DELAY_MS,
        max_delay_ms=MAX_DELAY_MS,
        repoll_ms=REPOLL_MS,
        silence_fallback_ms=60,
        transcript_timeout_ms=MAX_DELAY_MS,
        **profile_kwargs,
    )
    strategy = CascadingTurnStopStrategy(turn_analyzer=analyzer, profile=profile)
    await strategy.setup(fake_setup())
    return Harness(strategy, analyzer)


async def settle(seconds: float) -> None:
    await asyncio.sleep(seconds)


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------


async def test_max_delay_commits_when_smart_turn_never_answers():
    """The ceiling is what ends most turns. It must fire on its own."""
    h = await build()
    await h.transcript("I would like to check my order status please")
    speech_end = await h.speech_stopped()

    await settle(MAX_DELAY_MS / 1000 + 0.06)

    assert h.strategy.last_decision is TurnDecision.MAX_DELAY
    assert h.turn_stopped == 1
    assert h.inference_triggered == 1
    assert h.committed_at is not None
    assert h.committed_at - speech_end >= MAX_DELAY_MS / 1000


async def test_smart_turn_commits_before_the_ceiling():
    h = await build(verdicts=[EndOfTurnState.INCOMPLETE, EndOfTurnState.COMPLETE])
    await h.transcript("that is all thank you")
    speech_end = await h.speech_stopped()

    await settle(MAX_DELAY_MS / 1000)

    assert h.strategy.last_decision is TurnDecision.SMART_TURN
    assert h.turn_stopped == 1
    # Measured at the commit, not at the assertion: the point is that the model
    # ended the turn early, not that the test woke up early.
    assert h.committed_at is not None
    assert h.committed_at - speech_end < MAX_DELAY_MS / 1000


async def test_smart_turn_is_not_consulted_before_min_delay():
    """Below min_delay the caller is mid-breath; an inference there is wasted."""
    h = await build()
    speech_end = await h.speech_stopped()
    await settle(MAX_DELAY_MS / 1000 + 0.05)

    assert h.analyzer.poll_times, "Smart Turn was never polled"
    first_poll_delay = h.analyzer.poll_times[0] - speech_end
    assert first_poll_delay >= MIN_DELAY_MS / 1000 * 0.9


async def test_smart_turn_is_repolled_while_waiting():
    """One sample is not enough — the answer changes as silence accumulates."""
    h = await build()
    await h.speech_stopped()
    await settle(MAX_DELAY_MS / 1000 + 0.05)

    window = (MAX_DELAY_MS - MIN_DELAY_MS) / 1000
    expected = window / (REPOLL_MS / 1000)
    assert len(h.analyzer.poll_times) >= expected * 0.5
    assert len(h.analyzer.poll_times) <= expected + 3


async def test_deadline_is_anchored_to_real_end_of_speech():
    """VAD reports late by stop_secs; the ceiling must not drift by that much."""
    stop_secs = 0.05
    h = await build()
    speech_end = await h.speech_stopped(stop_secs=stop_secs)

    await settle(MAX_DELAY_MS / 1000 + 0.06)

    assert h.strategy.last_decision is TurnDecision.MAX_DELAY
    # The commit lands a max_delay after the caller actually stopped, not a
    # max_delay after VAD got round to saying so.
    assert time.time() - speech_end < MAX_DELAY_MS / 1000 + stop_secs + 0.09


async def test_resumed_speech_cancels_the_pending_commit():
    """A pause Smart Turn rejected is not the end of the turn."""
    h = await build()
    await h.speech_stopped()
    await settle(MIN_DELAY_MS / 1000 + 0.02)

    await h.speech_started()
    await settle(MAX_DELAY_MS / 1000 + 0.05)

    assert h.turn_stopped == 0
    assert h.strategy.last_decision is None


async def test_silence_fallback_when_smart_turn_is_disabled():
    """Outside the model's languages, never ask it — commit on silence."""
    h = await build(smart_turn=False)
    await h.transcript("hujambo naitaji msaada")
    await h.speech_stopped()

    await settle(0.12)

    assert h.strategy.last_decision is TurnDecision.SILENCE_FALLBACK
    assert h.turn_stopped == 1
    assert h.analyzer.poll_times == [], (
        "Smart Turn was polled for an unsupported language"
    )


async def test_turn_commits_only_once():
    h = await build(verdicts=[EndOfTurnState.COMPLETE])
    await h.speech_stopped()
    await settle(MAX_DELAY_MS / 1000 + 0.05)
    assert h.turn_stopped == 1


# ---------------------------------------------------------------------------
# Fragment handling at the ceiling
# ---------------------------------------------------------------------------


async def test_ceiling_fragment_is_reprompted_and_never_reaches_the_llm():
    """A confident answer to half a question is worse than asking again."""
    h = await build()
    await h.transcript("I want to check my")
    await h.speech_stopped()

    await settle(MAX_DELAY_MS / 1000 + 0.06)

    assert h.strategy.last_decision is TurnDecision.MAX_DELAY
    assert h.turn_stopped == 1, "the turn must still end"
    assert h.inference_triggered == 0, "a fragment must not run inference"
    assert h.reprompts() == ["Sorry, go ahead."]


async def test_ceiling_complete_utterance_runs_inference():
    h = await build()
    await h.transcript("I want to check the status of my delivery")
    await h.speech_stopped()

    await settle(MAX_DELAY_MS / 1000 + 0.06)

    assert h.inference_triggered == 1
    assert h.reprompts() == []


async def test_smart_turn_commit_skips_classification():
    """Only ceiling commits are suspect; if the model said done, it is done."""
    h = await build(verdicts=[EndOfTurnState.COMPLETE])
    await h.transcript("I want to check my")  # a fragment by the heuristic
    await h.speech_stopped()

    await settle(MAX_DELAY_MS / 1000)

    assert h.strategy.last_decision is TurnDecision.SMART_TURN
    assert h.inference_triggered == 1
    assert h.reprompts() == []


async def test_interim_only_is_reprompted_when_stt_wait_expires():
    """An interim cannot run inference: the user aggregator has no final text."""
    h = await build()
    await h.transcript("I need to check my delivery status", final=False)
    await h.speech_stopped()

    await settle(MAX_DELAY_MS / 1000 + 0.06)

    assert h.strategy.last_decision is TurnDecision.MAX_DELAY
    assert h.inference_triggered == 0
    assert h.reprompts() == ["Sorry, go ahead."]


async def test_a_ceiling_commit_with_no_transcript_at_all_is_reprompted():
    """Silence that VAD called speech must not turn into an empty LLM turn."""
    h = await build()
    await h.speech_stopped()

    await settle(MAX_DELAY_MS / 1000 + 0.06)

    assert h.inference_triggered == 0
    assert h.reprompts() == ["Sorry, go ahead."]


# ---------------------------------------------------------------------------
# Classifier, in isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I would like to check my order", Completeness.COMPLETE),
        ("I would like to check my", Completeness.FRAGMENT),
        ("send it to", Completeness.FRAGMENT),
        ("cancel it because", Completeness.FRAGMENT),
        ("yes", Completeness.COMPLETE),
        ("no", Completeness.COMPLETE),
        ("hello", Completeness.COMPLETE),
        ("um", Completeness.FRAGMENT),
        ("", Completeness.FRAGMENT),
        ("   ", Completeness.FRAGMENT),
        # Punctuation from the recogniser outranks the word heuristics: it saw
        # acoustics we did not.
        ("I want to check my.", Completeness.COMPLETE),
    ],
)
def test_fragment_heuristic(text, expected):
    classifier = HeuristicFragmentClassifier()
    assert classifier.classify(text, make_profile()) is expected


def test_classifier_vocabulary_is_per_language():
    """The dangling-token list comes from config, not from English hard-coding."""
    spanish = make_profile(
        "es",
        dangling_tokens=("y", "pero", "mi", "para"),
        complete_short=("sí", "no"),
    )
    classifier = HeuristicFragmentClassifier()
    assert classifier.classify("quiero revisar mi", spanish) is Completeness.FRAGMENT
    assert (
        classifier.classify("quiero revisar mi pedido", spanish)
        is Completeness.COMPLETE
    )
    assert classifier.classify("sí", spanish) is Completeness.COMPLETE
    # An English dangling token means nothing in Spanish.
    assert classifier.classify("revisar pedido and", spanish) is Completeness.COMPLETE


def test_profile_swap_changes_the_delays(profile):
    analyzer = FakeTurnAnalyzer()
    strategy = CascadingTurnStopStrategy(turn_analyzer=analyzer, profile=profile)
    assert strategy.profile.turn.max_delay_ms == 3000

    strategy.apply_profile(make_profile("uk", max_delay_ms=3400))
    assert strategy.profile.language == "uk"
    assert strategy.profile.turn.max_delay_ms == 3400


# ---------------------------------------------------------------------------
# Silence handler: the agent's own turnaround is not caller silence
# ---------------------------------------------------------------------------


async def test_silence_timer_does_not_run_while_the_agent_is_replying():
    """Regression: the agent asked "are you still there?" at callers who had
    just answered, because STT+LLM+TTS took longer than the silence threshold."""
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup

    from src.application.engine.turn.silence import SilenceHandler

    handler = SilenceHandler(profile=make_profile(), prompt_seconds=0.05, max_prompts=2)
    await handler.setup(
        FrameProcessorSetup(
            clock=None, task_manager=FakeTaskManager(), pipeline_worker=None
        )
    )
    spoken: list = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        spoken.append(frame)

    handler.push_frame = capture  # type: ignore[assignment]

    down = FrameDirection.DOWNSTREAM
    # Caller answers, then the pipeline takes longer than the threshold to reply.
    await handler.process_frame(UserStartedSpeakingFrame(), down)
    await handler.process_frame(UserStoppedSpeakingFrame(), down)
    await asyncio.sleep(0.15)

    assert handler.prompts_sent == 0, (
        "prompted the caller during the agent's own turnaround"
    )

    # Once the agent has actually spoken, the gap is the caller's again.
    await handler.process_frame(BotStartedSpeakingFrame(), down)
    await handler.process_frame(BotStoppedSpeakingFrame(), down)
    await asyncio.sleep(0.15)

    assert handler.prompts_sent == 1


async def test_slow_analyzer_cannot_extend_the_acoustic_deadline():
    class SlowAnalyzer(FakeTurnAnalyzer):
        async def analyze_end_of_turn(self):
            await asyncio.sleep(0.5)
            return EndOfTurnState.COMPLETE, None

    analyzer = SlowAnalyzer()
    strategy = CascadingTurnStopStrategy(
        turn_analyzer=analyzer,
        profile=make_profile(min_delay_ms=10, max_delay_ms=80),
    )
    await strategy.setup(fake_setup())
    h = Harness(strategy, analyzer)
    await h.transcript("please check my order status")
    began = await h.speech_stopped()
    await settle(0.16)
    assert h.turn_stopped == 1
    assert strategy.last_decision is TurnDecision.MAX_DELAY
    assert h.committed_at - began < 0.15
    await strategy.cleanup()


async def test_resuming_during_analysis_discards_its_pending_result():
    class SlowAnalyzer(FakeTurnAnalyzer):
        async def analyze_end_of_turn(self):
            await asyncio.sleep(0.12)
            return EndOfTurnState.COMPLETE, None

    analyzer = SlowAnalyzer()
    strategy = CascadingTurnStopStrategy(
        turn_analyzer=analyzer,
        profile=make_profile(min_delay_ms=10, max_delay_ms=300),
    )
    await strategy.setup(fake_setup())
    h = Harness(strategy, analyzer)
    await h.transcript("please check my order status")
    await h.speech_stopped()
    await settle(0.04)
    await h.speech_started()
    await settle(0.2)
    assert h.turn_stopped == 0
    await strategy.cleanup()
