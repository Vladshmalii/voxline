"""The silence handler's clock: whose quiet is it?

The prompt must fire on a caller who went away — and must not fire while the
pipeline itself is the quiet party: the greeting still being generated, or a
reply in flight after the caller's turn. Getting this wrong opens the call
with the agent asking "are you still there?" over its own greeting.
"""

from __future__ import annotations

from pipecat.frames.frames import Frame, LLMContextFrame, TTSSpeakFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.turn.silence import SilenceHandler
from tests.engine.conftest import make_profile


def build_handler(**kwargs) -> tuple[SilenceHandler, list[Frame]]:
    handler = SilenceHandler(profile=make_profile(), prompt_seconds=0, **kwargs)
    pushed: list[Frame] = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    handler.push_frame = collect  # type: ignore[method-assign]
    return handler, pushed


async def test_true_silence_draws_a_prompt():
    handler, pushed = build_handler()

    await handler._wait_and_prompt()

    prompts = [f for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert [p.text for p in prompts] == [handler._profile.spoken.silence]
    assert handler.prompts_sent == 1


async def test_a_reply_in_flight_is_not_caller_silence():
    """The greeting kickoff reaches the handler as a context frame with no
    user turn before it; the timer expiring mid-generation must stay quiet."""
    handler, pushed = build_handler()

    await handler.process_frame(
        LLMContextFrame(context=LLMContext()), FrameDirection.DOWNSTREAM
    )
    await handler._wait_and_prompt()

    assert not any(isinstance(f, TTSSpeakFrame) for f in pushed)
    assert handler.prompts_sent == 0


async def test_an_upstream_context_frame_does_not_freeze_the_clock():
    handler, _ = build_handler()

    await handler.process_frame(
        LLMContextFrame(context=LLMContext()), FrameDirection.UPSTREAM
    )

    assert handler._awaiting_response is False
