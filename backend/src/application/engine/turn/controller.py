"""Turn-taking controller: min delay, re-poll, hard ceiling, fragment classification.

Pipecat's stock :class:`TurnAnalyzerUserTurnStopStrategy` asks Smart Turn exactly
once, at the VAD stop, and then waits on transcripts. That is one sample of a
model whose answer changes as more silence accumulates, and it has no ceiling of
its own. This strategy replaces it with the cascade the design calls for::

    speech ends (Silero)
      │
      ├─ < min_delay ........... do not ask. The caller is mid-breath and an
      │                          inference here is spent on a foregone answer.
      ├─ min_delay .. max_delay  ask Smart Turn every repoll_ms
      │     ├─ p >= threshold .. acoustic turn complete
      │     └─ p <  threshold .. keep listening
      └─ max_delay ............. acoustic turn complete regardless

An acoustic decision dispatches the LLM only once the transcript is ready.
Provider TTFS metadata bounds the wait for non-finalized segments; a finalized
transcript skips that wait. An interim or resumed speech invalidates an earlier
final. Missing text is re-prompted at ``transcript_timeout_ms`` instead of
closing an empty turn and reopening it when a late transcript arrives.

**max_delay is load-bearing.** Smart Turn v3.2 runs about 58.9% recall and 68.4%
precision, so on a large fraction of turns the model never returns a confident
"finished" and the ceiling is what actually ends the turn. It is normal
operation, not an error path — which is why a commit at the ceiling gets treated
differently from one the model asked for: the transcript is classified first, and
a fragment gets a short localised re-prompt instead of an LLM turn. Sending a
fragment to the LLM produces a confident answer to half a question, which is
worse than asking the caller to repeat.

Languages outside Smart Turn's coverage skip the model entirely and commit on a
tuned silence threshold (``silence_fallback_ms``). Asking a model about a
language it never saw returns noise, and noise at 400 ms intervals is expensive
noise.
"""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import Protocol

from loguru import logger
from pipecat.audio.turn.base_turn_analyzer import BaseTurnAnalyzer, EndOfTurnState
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    MetricsFrame,
    SpeechControlParamsFrame,
    StartFrame,
    STTMetadataFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.services.stt_latency import DEFAULT_TTFS_P99
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_stop.base_user_turn_stop_strategy import (
    BaseUserTurnStopStrategy,
)
from pipecat.utils.string import SENTENCE_ENDING_PUNCTUATION

from src.application.engine.config import ResolvedProfile


class TurnDecision(StrEnum):
    """Why a turn was committed."""

    SMART_TURN = "smart_turn"
    """The model said the caller had finished."""

    MAX_DELAY = "max_delay"
    """The ceiling fired. Expect this often — see the module docstring."""

    SILENCE_FALLBACK = "silence_fallback"
    """Smart Turn is disabled for this language; committed on silence."""

    ANALYZER_SILENCE = "analyzer_silence"
    """The analyzer's own silence timer fired before ours did."""


class Completeness(StrEnum):
    """Whether a committed transcript is worth sending to the LLM."""

    COMPLETE = "complete"
    FRAGMENT = "fragment"


class FragmentClassifier(Protocol):
    """Decides whether a transcript is a whole request or a piece of one.

    Kept behind a protocol so the heuristic can be swapped for a small model
    without touching the controller. It runs *after* the ceiling has fired, when
    the agent is about to speak either way, so it is off the critical path and
    can afford tens of milliseconds — but not hundreds.
    """

    def classify(self, text: str, profile: ResolvedProfile) -> Completeness:
        """Classify `text` under `profile`'s language conventions."""
        ...


class HeuristicFragmentClassifier:
    """Word-count and dangling-token heuristic, driven entirely by config.

    Three signals, cheapest first:

    1. The transcript ends in sentence-ending punctuation — the recogniser
       thought it was a sentence, and it has the acoustics we do not.
    2. The last word is a conjunction, article, preposition or filler
       (``dangling_tokens``). "I want to check my" is unambiguously mid-sentence.
    3. It is shorter than ``min_words`` and is not one of the short utterances
       that are nonetheless complete turns (``complete_short``: yes, no, hello).
    """

    def classify(self, text: str, profile: ResolvedProfile) -> Completeness:
        """Classify a transcript. See the class docstring for the rules."""
        stripped = text.strip()
        if not stripped:
            return Completeness.FRAGMENT

        if stripped[-1] in SENTENCE_ENDING_PUNCTUATION:
            return Completeness.COMPLETE

        params = profile.fragment
        words = [
            w.strip("".join(SENTENCE_ENDING_PUNCTUATION) + ",;:—–\"'()")
            for w in stripped.split()
        ]
        words = [w.lower() for w in words if w]
        if not words:
            return Completeness.FRAGMENT

        if words[-1] in params.dangling_tokens:
            return Completeness.FRAGMENT

        if len(words) < params.min_words:
            if any(w in params.complete_short for w in words):
                return Completeness.COMPLETE
            return Completeness.FRAGMENT

        return Completeness.COMPLETE


class CascadingTurnStopStrategy(BaseUserTurnStopStrategy):
    """Ends the caller's turn using the min/repoll/max cascade above.

    Install in place of Pipecat's ``TurnAnalyzerUserTurnStopStrategy``::

        strategy = CascadingTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3(), profile=...)
        UserTurnStrategies(stop=[strategy])

    The active language profile can be swapped mid-call with
    :meth:`apply_profile`; it takes effect from the next turn.
    """

    def __init__(
        self,
        *,
        turn_analyzer: BaseTurnAnalyzer | None,
        profile: ResolvedProfile,
        classifier: FragmentClassifier | None = None,
        **kwargs,
    ) -> None:
        """Initialise the strategy.

        Args:
            turn_analyzer: Smart Turn v3 (or any ``BaseTurnAnalyzer``).
            profile: Language profile supplying the three delays and the
                fragment-classification vocabulary.
            classifier: Fragment classifier; defaults to the heuristic one.
            **kwargs: Passed to :class:`BaseUserTurnStopStrategy`.
        """
        super().__init__(**kwargs)
        self._turn_analyzer = turn_analyzer
        self._profile = profile
        self._classifier: FragmentClassifier = (
            classifier or HeuristicFragmentClassifier()
        )

        self._vad_user_speaking = False
        self._committed = False
        self._poll_task: asyncio.Task | None = None
        self._text = ""
        self._last_decision: TurnDecision | None = None
        self._final_parts: list[str] = []
        self._final_count_at_speech_start = 0
        self._interim = ""
        self._transcript_finalized = False
        self._stt_timeout = DEFAULT_TTFS_P99
        self._speech_end: float | None = None
        self._pending_decision: TurnDecision | None = None
        self._transcript_task: asyncio.Task | None = None
        self._suppress_inference = False

    @property
    def suppress_inference(self) -> bool:
        """Whether this completed turn is answered by a local re-prompt.

        Kept through handle_user_turn_stopped: Pipecat resets strategies before
        asking the user aggregator to flush the completed turn into context.
        """
        return self._suppress_inference

    # -- configuration -----------------------------------------------------

    @property
    def profile(self) -> ResolvedProfile:
        """The language profile currently in force."""
        return self._profile

    @property
    def last_decision(self) -> TurnDecision | None:
        """Why the most recent turn committed. Useful in tests and logs."""
        return self._last_decision

    def apply_profile(self, profile: ResolvedProfile) -> None:
        """Switch to another language's turn parameters.

        Applies from the next turn; a poll already in flight keeps the timings it
        started with, so a mid-turn language switch cannot move a deadline that
        has already passed.
        """
        self._profile = profile
        logger.debug(
            f"turn: profile={profile.language} smart_turn={profile.turn.smart_turn} "
            f"min={profile.turn.min_delay_ms}ms max={profile.turn.max_delay_ms}ms "
            f"repoll={profile.turn.repoll_ms}ms"
        )

    # -- lifecycle ---------------------------------------------------------

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Bind the strategy to the pipeline and adopt its input rate.

        The rate comes from the setup rather than the ``StartFrame``, whose
        copy is deprecated since Pipecat 1.8.0 — the same move upstream's own
        ``TurnAnalyzerUserTurnStopStrategy`` made.
        """
        await super().setup(setup)
        if self._turn_analyzer is not None:
            self._turn_analyzer.set_sample_rate(setup.audio_in_sample_rate)

    async def cleanup(self) -> None:
        """Cancel any poll in flight and release the analyzer."""
        await super().cleanup()
        await self._cancel_poll()
        await self._cancel_transcript_wait()
        if self._turn_analyzer is not None:
            await self._turn_analyzer.cleanup()

    async def handle_user_turn_started(self) -> None:
        """Arm for a new turn."""
        await self._reset()
        self._suppress_inference = False

    async def handle_user_turn_stopped(self) -> None:
        """Tear down after a turn, whoever ended it.

        Also drops the analyzer's buffered speech: a turn ended from outside
        (a mute strategy, the controller's watchdog) would otherwise leave a
        silence timer running that fires a phantom end-of-turn into the next one.
        """
        await self._reset()
        if self._turn_analyzer is not None:
            self._turn_analyzer.clear()

    async def _reset(self) -> None:
        self._text = ""
        self._final_parts.clear()
        self._final_count_at_speech_start = 0
        self._interim = ""
        self._transcript_finalized = False
        self._speech_end = None
        self._pending_decision = None
        self._committed = False
        await self._cancel_poll()
        await self._cancel_transcript_wait()

    async def _cancel_transcript_wait(self) -> None:
        task, self._transcript_task = self._transcript_task, None
        if task is not None and task is not asyncio.current_task():
            await self.task_manager.cancel_task(task)

    async def _cancel_poll(self) -> None:
        task, self._poll_task = self._poll_task, None
        if task is not None and task is not asyncio.current_task():
            await self.task_manager.cancel_task(task)

    # -- frame handling ----------------------------------------------------

    async def process_frame(self, frame: Frame) -> ProcessFrameResult:
        """Feed the analyzer and drive the cascade.

        Returns:
            Always ``CONTINUE`` so any other configured stop strategy still runs.
        """
        if isinstance(frame, StartFrame) and self._turn_analyzer is not None:
            await self.broadcast_frame(
                SpeechControlParamsFrame, turn_params=self._turn_analyzer.params
            )
        elif isinstance(frame, STTMetadataFrame):
            self._stt_timeout = max(0.0, frame.ttfs_p99_latency)
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            await self._handle_speech_started(frame)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            await self._handle_speech_stopped(frame)
        elif isinstance(frame, InputAudioRawFrame):
            await self._handle_audio(frame)
        elif (
            isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame))
            and frame.text.strip()
        ):
            if isinstance(frame, TranscriptionFrame):
                self._final_parts.append(frame.text.strip())
                self._interim = ""
                self._transcript_finalized = frame.finalized
            else:
                self._interim = frame.text.strip()
                # More text is coming; a previous segment's final no longer
                # covers the whole utterance.
                self._transcript_finalized = False
            self._text = " ".join([*self._final_parts, self._interim]).strip()
            if self._speech_end is None and not self._vad_user_speaking:
                # Soft speech can produce text without any VAD transition.
                # Coalesce segments, then finish without the 5s watchdog.
                await self._cancel_poll()
                self._poll_task = self.task_manager.create_task(
                    self._transcript_only(), f"{self}::_transcript_only"
                )
            await self._maybe_finish_turn()

        return ProcessFrameResult.CONTINUE

    async def _handle_speech_started(self, frame: VADUserStartedSpeakingFrame) -> None:
        if self._turn_analyzer is not None:
            self._turn_analyzer.update_vad_start_secs(frame.start_secs)
        self._vad_user_speaking = True
        # The caller resumed. Any conclusion reached during the pause is stale,
        # and the deadline restarts from the new end of speech.
        self._committed = False
        self._pending_decision = None
        self._speech_end = None
        self._transcript_finalized = False
        self._final_count_at_speech_start = len(self._final_parts)
        await self._cancel_poll()
        await self._cancel_transcript_wait()

    async def _handle_speech_stopped(self, frame: VADUserStoppedSpeakingFrame) -> None:
        self._vad_user_speaking = False

        # VAD reports the stop `stop_secs` after the caller actually fell silent.
        # Anchoring every deadline to the true end of speech keeps min_delay and
        # max_delay meaning what they say, regardless of how VAD is tuned or how
        # long an inference takes.
        speech_end = frame.timestamp - frame.stop_secs
        self._speech_end = time.monotonic() - max(0.0, time.time() - speech_end)

        await self._cancel_poll()
        self._poll_task = self.task_manager.create_task(
            self._poll(speech_end), f"{self}::_poll"
        )

    async def _handle_audio(self, frame: InputAudioRawFrame) -> None:
        if self._turn_analyzer is None:
            return
        state = self._turn_analyzer.append_audio(frame.audio, self._vad_user_speaking)
        # Streaming analyzers decide frame-by-frame here; batch analyzers only
        # return COMPLETE from a silence timeout. Either way this is the
        # analyzer's own ceiling firing before ours, which normally means its
        # stop_secs is configured below our max_delay (see bot.py).
        if state == EndOfTurnState.COMPLETE:
            _, prediction = await self._turn_analyzer.analyze_end_of_turn()
            await self._publish_metrics(prediction)
            await self._commit(TurnDecision.ANALYZER_SILENCE)

    # -- the cascade -------------------------------------------------------

    async def _poll(self, speech_end: float) -> None:
        """Wait out min_delay, then re-poll Smart Turn until it answers or time runs out."""
        params = self._profile.turn

        if not params.smart_turn or self._turn_analyzer is None:
            # No model for this language. Commit on silence alone.
            await self._sleep_until(speech_end + params.silence_fallback)
            await self._commit(TurnDecision.SILENCE_FALLBACK)
            return

        deadline = speech_end + params.max_delay
        logger.debug(
            f"turn: pause detected, floor={params.min_delay_ms}ms ceiling={params.max_delay_ms}ms "
            "— below floor, treating as a breath"
        )
        await self._sleep_until(speech_end + params.min_delay)

        while True:
            if time.time() >= deadline:
                await self._commit(TurnDecision.MAX_DELAY)
                return

            try:
                async with asyncio.timeout(max(0.0, deadline - time.time())):
                    state, prediction = await self._turn_analyzer.analyze_end_of_turn()
            except TimeoutError:
                await self._commit(TurnDecision.MAX_DELAY)
                return
            await self._publish_metrics(prediction)

            if state == EndOfTurnState.COMPLETE:
                await self._commit(TurnDecision.SMART_TURN)
                return

            remaining = deadline - time.time()
            if remaining <= 0:
                await self._commit(TurnDecision.MAX_DELAY)
                return
            logger.debug(
                f"turn: analyzer inconclusive {time.time() - speech_end:.2f}s since speech end, "
                f"repolling in {params.repoll_ms}ms ({remaining:.2f}s left until ceiling)"
            )
            await asyncio.sleep(min(params.repoll_interval, remaining))

    @staticmethod
    async def _sleep_until(when: float) -> None:
        delay = when - time.time()
        if delay > 0:
            await asyncio.sleep(delay)

    async def _publish_metrics(self, prediction) -> None:
        if prediction:
            await self.push_frame(MetricsFrame(data=[prediction]))

    async def _commit(self, decision: TurnDecision) -> None:
        """Record the acoustic decision; dispatch only when STT is ready."""
        if self._committed or self._vad_user_speaking:
            return
        if decision is TurnDecision.MAX_DELAY:
            since_speech_end = (
                time.monotonic() - self._speech_end
                if self._speech_end is not None
                else 0.0
            )
            logger.debug(
                f"turn: ceiling ({self._profile.turn.max_delay_ms}ms) reached "
                f"{since_speech_end:.2f}s since speech end, committing regardless"
            )
        await self._cancel_poll()
        self._pending_decision = decision
        if self._speech_end is None:
            self._speech_end = time.monotonic()
        await self._maybe_finish_turn()
        if self._pending_decision is not None and self._transcript_task is None:
            self._transcript_task = self.task_manager.create_task(
                self._wait_for_transcript(), f"{self}::_wait_for_transcript"
            )

    async def _transcript_only(self) -> None:
        await asyncio.sleep(self._stt_timeout)
        self._speech_end = time.monotonic() - self._stt_timeout
        await self._commit(TurnDecision.SILENCE_FALLBACK)

    async def _wait_for_transcript(self) -> None:
        # The soft deadline is provider metadata; the hard deadline bounds
        # broken/missing STT. Both run concurrently with acoustic end detection.
        for budget in (
            self._stt_timeout,
            self._profile.turn.transcript_timeout_ms / 1000,
        ):
            if self._speech_end is None:
                return
            hard = self._profile.turn.transcript_timeout_ms / 1000
            await asyncio.sleep(
                max(0.0, self._speech_end + min(budget, hard) - time.monotonic())
            )
            await self._maybe_finish_turn()
            if self._pending_decision is None:
                return

    async def _maybe_finish_turn(self) -> None:
        if self._pending_decision is None or self._vad_user_speaking or self._committed:
            return
        elapsed = time.monotonic() - self._speech_end
        ready = (
            len(self._final_parts) > self._final_count_at_speech_start
            and not self._interim
            and (self._transcript_finalized or elapsed >= self._stt_timeout)
        )
        timed_out = elapsed >= self._profile.turn.transcript_timeout_ms / 1000
        if not ready and not timed_out:
            return

        decision = self._pending_decision
        self._pending_decision = None
        self._committed = True
        self._last_decision = decision
        await self._cancel_transcript_wait()

        text = self._text.strip()
        self._suppress_inference = not ready or (
            decision is TurnDecision.MAX_DELAY
            and self._classifier.classify(text, self._profile) is Completeness.FRAGMENT
        )
        logger.info(
            f"turn committed on {decision} ({self._profile.language}): "
            f"reprompt={self._suppress_inference} — {text[:80]!r}"
        )
        if self._suppress_inference:
            await self.trigger_user_turn_finalized()
            await self.push_frame(TTSSpeakFrame(self._profile.spoken.reprompt))
            return
        await self.trigger_user_turn_stopped()
