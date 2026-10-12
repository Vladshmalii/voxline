"""Pipecat's context writes, with explicit support for local re-prompts."""

from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregator
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.turn.controller import CascadingTurnStopStrategy


class CallUserAggregator(LLMUserAggregator):
    """Save a rejected/incomplete turn without dispatching another LLM request.

    Pipecat 1.7 flushes aggregation on both inference and finalization. Suppress
    only the context *dispatch* during this finalization callback, preserving
    the transcript, timestamps and public turn events from the base class.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._suppress_context_dispatch = False

    async def _on_user_turn_stopped(self, controller, strategy, params):
        self._suppress_context_dispatch = (
            isinstance(strategy, CascadingTurnStopStrategy)
            and strategy.suppress_inference
        )
        try:
            await super()._on_user_turn_stopped(controller, strategy, params)
        finally:
            self._suppress_context_dispatch = False

    async def push_context_frame(self, direction=FrameDirection.DOWNSTREAM):
        if not self._suppress_context_dispatch:
            await super().push_context_frame(direction)
