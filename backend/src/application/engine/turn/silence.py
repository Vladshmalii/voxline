"""Silence handler: speak first when the caller does not, and hang up if nobody ever does.

Without this, a call answered by voicemail — or by someone who put the handset
down — holds the leg open until the telephony provider's timeout, minutes later,
paying for a channel and an ASR connection that will never carry a word.

The behaviour is deliberately dumb, because it runs when the smart parts have
nothing to work with:

* ``SILENCE_PROMPT_SECONDS`` of silence with neither party speaking → say the
  localised silence prompt.
* After ``SILENCE_MAX_PROMPTS`` unanswered prompts → say goodbye and end the call.
* Any speech from the caller resets the counter to zero.

The model's end_call tool shares this shutdown state, suspending silence prompts
while its farewell plays. Its interruptible marker, checked after paced output,
prevents an earlier BotStoppedSpeakingFrame from ending the call too soon.

Note this is *not* answering-machine detection, which is explicitly out of scope.
It is the crude backstop that makes the absence of AMD survivable.
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    EndWorkerFrame,
    Frame,
    FunctionCallResultProperties,
    InterruptionFrame,
    LLMContextFrame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams

from src.application.engine.call_end import CallEndFrame
from src.application.engine.config import ResolvedProfile

#: If TTS never produces audio for the goodbye, end anyway after this long.
#: A silence handler that hangs waiting on a broken TTS is worse than no silence
#: handler at all — it fails in exactly the case it exists to cover.
_GOODBYE_TIMEOUT_SECS = 10.0


class SilenceHandler(FrameProcessor):
    """Prompts the caller after silence, and closes the call after too much of it."""

    def __init__(
        self,
        *,
        profile: ResolvedProfile,
        prompt_seconds: float = 9.0,
        max_prompts: int = 2,
        **kwargs,
    ) -> None:
        """Initialise the handler.

        Args:
            profile: Language profile supplying the localised prompt and goodbye.
            prompt_seconds: Silence to tolerate before prompting.
            max_prompts: Unanswered prompts before hanging up.
            **kwargs: Passed to :class:`FrameProcessor`.
        """
        super().__init__(**kwargs)
        self._profile = profile
        self._prompt_seconds = prompt_seconds
        self._max_prompts = max_prompts

        self._prompts_sent = 0
        self._timer: asyncio.Task | None = None
        #: When the current silence timer started waiting, for diagnosing how
        #: long a gap actually was when the caller interrupts it. None while no
        #: timer is running.
        self._timer_started_at: float | None = None
        self._closing = False
        self._user_speaking = False
        self._bot_speaking = False
        # True between the caller's turn ending and the agent's reply finishing:
        # the gap belongs to the pipeline, not to caller silence.
        self._awaiting_response = False
        self._end_call_request: int | None = None
        self._ended = False

    @property
    def prompts_sent(self) -> int:
        """Unanswered prompts spoken so far on this call."""
        return self._prompts_sent

    def apply_profile(self, profile: ResolvedProfile) -> None:
        """Switch to another language's prompts."""
        self._profile = profile

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Track who is speaking and run the silence timer."""
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            await self._restart_timer()
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            self._end_call_request = None
            self._ended = True
            await self._cancel_timer()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStartedSpeakingFrame):
            if self._timer_started_at is not None:
                logger.debug(
                    f"silence: caller started speaking after "
                    f"{time.monotonic() - self._timer_started_at:.2f}s of quiet, "
                    f"resetting prompt counter ({self._prompts_sent}/{self._max_prompts} -> 0)"
                )
            self._user_speaking = True
            self._awaiting_response = False
            # The caller is there. Everything we were counting is void.
            self._prompts_sent = 0
            self._closing = False
            self._end_call_request = None
            await self._cancel_timer()
        elif (
            isinstance(frame, InterruptionFrame) and self._end_call_request is not None
        ):
            self._end_call_request = None
            self._closing = False
            await self._cancel_timer()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            # Deliberately NOT restarting the timer here. Between the caller
            # finishing and the agent replying, nobody is speaking — but that is
            # the agent thinking, not the caller going quiet. Counting it as
            # silence makes the agent interrupt its own turnaround with "are you
            # still there?" whenever STT plus LLM plus TTS exceed the threshold,
            # which reads to the caller as the agent talking over them after
            # they answered promptly. The timer restarts when the agent has
            # actually finished speaking; a pipeline that never replies is the
            # PipelineWorker idle timeout's problem, not this one's.
            self._awaiting_response = True
        elif (
            isinstance(frame, LLMContextFrame)
            and direction == FrameDirection.DOWNSTREAM
        ):
            # A reply is in flight: every LLM run passes here as the context
            # frame on its way downstream. The greeting kickoff arrives this
            # way with no user turn before it, so the UserStoppedSpeaking
            # branch above never saw it — and on a cold model the time to
            # first audio exceeds any sane prompt threshold, making the agent
            # open the call by asking "are you still there?" over its own
            # greeting. The clock resumes at BotStoppedSpeaking.
            self._awaiting_response = True
            await self._cancel_timer()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            if self._end_call_request is None:
                await self._cancel_timer()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            # The agent has replied; the gap that follows is genuinely the
            # caller's to fill, so the timer runs again from here.
            self._awaiting_response = False
            if self._closing and self._end_call_request is None:
                await self.push_frame(frame, direction)
                await self._end_call()
                return
            await self._restart_timer()

        await self.push_frame(frame, direction)

    async def handle_end_call(self, params: FunctionCallParams) -> None:
        """Reserve a goodbye, then speak after the tool result is in history."""
        goodbye = params.arguments.get("goodbye")
        if not isinstance(goodbye, str) or len(goodbye) > 300:
            await params.result_callback(
                {"error": "goodbye must be a string of at most 300 characters"},
                properties=FunctionCallResultProperties(run_llm=True),
            )
            return
        if self._closing or self._ended or self._user_speaking:
            await params.result_callback(
                {
                    "status": "not_scheduled",
                    "reason": "already closing or caller speaking",
                },
                properties=FunctionCallResultProperties(run_llm=False),
            )
            return

        marker = CallEndFrame()
        self._end_call_request = marker.id
        self._closing = True
        await self._cancel_timer()
        self._timer = self.create_task(self._goodbye_watchdog(timeout=30.0))

        async def speak_goodbye() -> None:
            # A tool result is uninterruptible and may arrive after the user
            # has resumed speaking. Never revive that cancelled request.
            if self._end_call_request != marker.id or self._ended:
                return
            logger.info("end_call: speaking farewell before ending the call")
            await self.push_frame(
                TTSSpeakFrame(goodbye.strip() or self._profile.spoken.goodbye)
            )
            await self.push_frame(marker)

        await params.result_callback(
            {"status": "ending_after_goodbye", "interruption_cancels": True},
            properties=FunctionCallResultProperties(
                run_llm=False, on_context_updated=speak_goodbye
            ),
        )

    async def complete_end_call(self, request_id: int) -> None:
        """Only the matching marker after paced output can finish this request."""
        if self._end_call_request == request_id and not self._user_speaking:
            await self._end_call()

    # -- timer -------------------------------------------------------------

    async def _restart_timer(self) -> None:
        if self._ended or self._closing or self._user_speaking or self._bot_speaking:
            return
        if self._awaiting_response:
            return
        await self._cancel_timer()
        self._timer_started_at = time.monotonic()
        self._timer = self.create_task(self._wait_and_prompt())

    async def _cancel_timer(self) -> None:
        # Always through cancel_task: tasks created via FrameProcessor.create_task
        # are registered with the pipeline's task manager, and cancelling one
        # directly leaves it dangling in that registry.
        task, self._timer = self._timer, None
        self._timer_started_at = None
        if task is not None and task is not asyncio.current_task():
            await self.cancel_task(task)

    async def _wait_and_prompt(self) -> None:
        await asyncio.sleep(self._prompt_seconds)
        self._timer = None

        if (
            self._user_speaking
            or self._bot_speaking
            or self._closing
            or self._awaiting_response
        ):
            return

        if self._prompts_sent >= self._max_prompts:
            await self._say_goodbye()
            return

        self._prompts_sent += 1
        logger.info(
            f"silence: no speech for {self._prompt_seconds}s, "
            f"prompting ({self._prompts_sent}/{self._max_prompts})"
        )
        await self.push_frame(TTSSpeakFrame(self._profile.spoken.silence))
        # No timer restart here: BotStoppedSpeakingFrame restarts it once the
        # prompt has actually been spoken, so the window is silence the caller
        # had a chance to fill rather than time spent talking over them.

    async def _say_goodbye(self) -> None:
        logger.info(
            f"silence: {self._prompts_sent} prompts unanswered, closing the call"
        )
        self._closing = True
        await self.push_frame(TTSSpeakFrame(self._profile.spoken.goodbye))
        self._timer = self.create_task(self._goodbye_watchdog())

    async def _goodbye_watchdog(self, timeout: float = _GOODBYE_TIMEOUT_SECS) -> None:
        await asyncio.sleep(timeout)
        self._timer = None
        if self._closing:
            logger.warning(
                "silence: goodbye never finished playing; ending the call anyway"
            )
            await self._end_call()

    async def _end_call(self) -> None:
        if not self._closing:
            return
        self._closing = False
        self._end_call_request = None
        self._ended = True
        await self._cancel_timer()
        # Upstream: the pipeline task owns shutdown, and an EndWorkerFrame there
        # drains queued output before tearing the pipeline down.
        await self.push_frame(EndWorkerFrame(), FrameDirection.UPSTREAM)
