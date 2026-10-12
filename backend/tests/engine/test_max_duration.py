"""Hard call-length cap: fires by wall-clock, waits for a quiet moment to act.

Distinct from the silence handler (test_silence.py, test_connect_and_feedback_
silence.py), which only fires on inactivity — this timer runs regardless of
how engaged the caller is, and must not interrupt an in-progress turn.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndWorkerFrame,
    Frame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.turn.max_duration import MaxDurationHandler


def build_handler(
    *, max_duration_seconds: float | None = 0, goodbye: str = "Goodbye."
) -> tuple[MaxDurationHandler, list[Frame]]:
    handler = MaxDurationHandler(
        max_duration_seconds=max_duration_seconds, goodbye=goodbye
    )
    pushed: list[Frame] = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    handler.push_frame = collect  # type: ignore[method-assign]

    # Tests drive `_wait_and_end`/`_try_close` directly; a frame that triggers
    # the class's own scheduling (e.g. StartFrame) must not also spawn a real
    # background timer task racing the explicit call below.
    def noop_create_task(coro):
        coro.close()

    handler.create_task = noop_create_task  # type: ignore[method-assign]
    return handler, pushed


async def test_cap_reached_during_a_quiet_moment_ends_the_call():
    handler, pushed = build_handler()

    await handler._try_close()
    assert [f.text for f in pushed if isinstance(f, TTSSpeakFrame)] == ["Goodbye."]
    assert handler._closing is True

    # The goodbye actually being spoken is what ends the call, same mechanics
    # as the silence handler's own goodbye.
    await handler.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert any(isinstance(f, EndWorkerFrame) for f in pushed)


async def test_cap_reached_mid_bot_turn_waits_for_it_to_finish():
    handler, pushed = build_handler()

    await handler.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await handler._wait_and_end()

    assert not any(isinstance(f, TTSSpeakFrame) for f in pushed)
    assert handler._due is True

    # The bot's own turn finishing triggers the deferred close, not a second
    # goodbye stacked on top of the one still in flight.
    await handler.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert [f.text for f in pushed if isinstance(f, TTSSpeakFrame)] == ["Goodbye."]


async def test_cap_reached_mid_caller_turn_waits_for_it_to_finish():
    handler, pushed = build_handler()

    await handler.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await handler._wait_and_end()

    assert not any(isinstance(f, TTSSpeakFrame) for f in pushed)

    await handler.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert [f.text for f in pushed if isinstance(f, TTSSpeakFrame)] == ["Goodbye."]


async def test_unset_cap_never_schedules_a_timer():
    handler, pushed = build_handler(max_duration_seconds=None)

    await handler.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

    assert handler._timer is None
    assert any(isinstance(f, StartFrame) for f in pushed)
