"""Hard cap on total call length, independent of how engaged the caller is.

Distinct from two other timers that can end a call:

* ``PipelineWorker``'s own ``idle_timeout_secs`` (``pipeline.py``) fires when
  neither side has produced a frame for that long — it does nothing while the
  conversation is active.
* The silence handler's prompt/goodbye cascade (``turn/silence.py``) fires
  when the *caller* goes quiet — it never fires while they keep talking.

This timer runs from ``StartFrame`` unconditionally, counts wall-clock time
regardless of activity, and does not reset on speech from either side. It
exists for cost and duration control: an operator caps how long any one call
may run, independent of engagement. ``None`` (the default) means no cap — the
only remaining backstop is the platform-wide
``CallWorkerSettings.max_call_seconds`` sweep, which cleans up the database
bookkeeping for a leaked leg every minute but does not itself end a live call
(``application/worker/tasks.py``'s ``sweep_calls``).

When the cap is reached, the handler waits for a quiet moment (neither side
mid-turn) rather than talking over an in-progress exchange, then speaks
``spoken_goodbye`` and ends the call — the same phrase and shutdown mechanics
as the silence handler's own goodbye, so a caller hears one consistent way of
being told the call is over regardless of which timer triggered it.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    EndWorkerFrame,
    Frame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

#: If TTS never produces audio for the goodbye, end anyway after this long.
#: Mirrors ``turn/silence.py``'s own watchdog for the identical failure mode.
_GOODBYE_TIMEOUT_SECS = 10.0


class MaxDurationHandler(FrameProcessor):
    """Ends the call after ``max_duration_seconds``, saying ``goodbye`` first."""

    def __init__(
        self,
        *,
        max_duration_seconds: float | None,
        goodbye: str,
        **kwargs,
    ) -> None:
        """Initialise the handler.

        Args:
            max_duration_seconds: Wall-clock seconds after which the call is
                ended, counted from ``StartFrame``. None (or 0) disables the
                cap entirely — no timer is scheduled.
            goodbye: The line to speak before ending — the same
                ``spoken_goodbye`` phrase the silence handler uses.
            **kwargs: Passed to :class:`FrameProcessor`.
        """
        super().__init__(**kwargs)
        self._max_duration_seconds = max_duration_seconds
        self._goodbye = goodbye

        self._timer: asyncio.Task | None = None
        self._closing = False
        #: The cap fired, but a quiet moment hasn't arrived yet to act on it.
        self._due = False
        self._user_speaking = False
        self._bot_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Track who is speaking and run the cap timer."""
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            if self._max_duration_seconds:
                self._timer = self.create_task(self._wait_and_end())
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._cancel_timer()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            if self._due:
                await self._try_close()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            if self._closing:
                await self.push_frame(frame, direction)
                await self._end_call()
                return
            if self._due:
                await self._try_close()

        await self.push_frame(frame, direction)

    # -- timer ---------------------------------------------------------------

    async def _cancel_timer(self) -> None:
        # Always through cancel_task: tasks created via FrameProcessor.create_task
        # are registered with the pipeline's task manager, and cancelling one
        # directly leaves it dangling in that registry.
        task, self._timer = self._timer, None
        if task is not None and task is not asyncio.current_task():
            await self.cancel_task(task)

    async def _wait_and_end(self) -> None:
        await asyncio.sleep(self._max_duration_seconds)
        self._timer = None
        self._due = True
        await self._try_close()

    async def _try_close(self) -> None:
        """Say goodbye and end, once neither side is mid-turn."""
        if self._closing or self._user_speaking or self._bot_speaking:
            return
        logger.info(
            f"max_duration: call reached {self._max_duration_seconds}s, ending it"
        )
        self._closing = True
        await self.push_frame(TTSSpeakFrame(self._goodbye))
        self._timer = self.create_task(self._goodbye_watchdog())

    async def _goodbye_watchdog(self) -> None:
        await asyncio.sleep(_GOODBYE_TIMEOUT_SECS)
        self._timer = None
        if self._closing:
            logger.warning(
                "max_duration: goodbye never finished playing; ending the call anyway"
            )
            await self._end_call()

    async def _end_call(self) -> None:
        if not self._closing:
            return
        self._closing = False
        await self._cancel_timer()
        # Upstream: the pipeline task owns shutdown, and an EndWorkerFrame there
        # drains queued output before tearing the pipeline down.
        await self.push_frame(EndWorkerFrame(), FrameDirection.UPSTREAM)
