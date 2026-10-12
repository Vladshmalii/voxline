"""An interruptible playback marker for model-requested call termination."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import DataFrame, Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams


@dataclass
class CallEndFrame(DataFrame):
    """Reaches the pipeline tail only after the goodbye audio has played.

    Unlike EndWorkerFrame, this marker is discarded on interruption. The
    request id is also checked at the tail, covering a marker already in flight.
    """


class CallEndGate(FrameProcessor):
    """Convert a still-current playback marker into graceful worker shutdown."""

    def __init__(self, complete: Callable[[int], Awaitable[None]]) -> None:
        super().__init__()
        self._complete = complete

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, CallEndFrame) and direction == FrameDirection.DOWNSTREAM:
            await self._complete(frame.id)
        else:
            await self.push_frame(frame, direction)


def end_call_tool(
    handler: Callable[[FunctionCallParams], Awaitable[None]],
) -> FunctionSchema:
    return FunctionSchema(
        name="end_call",
        description=(
            "End this phone call after speaking a brief goodbye. Use when the caller "
            "asks to hang up, declines to continue, says goodbye, or the conversation "
            "is complete with no outstanding questions or actions. Do not use for "
            "silence, a pause, an unclear answer, or while the caller still needs help. "
            "Finish any other tool actions before calling this tool; do not call it "
            "in parallel with other tools. Supply the goodbye here instead of saying "
            "it separately. The system speaks it and disconnects after playback. "
            "If the caller interrupts before disconnection, ending is cancelled "
            "and you should respond to them normally."
        ),
        properties={
            "goodbye": {
                "type": "string",
                "maxLength": 300,
                "description": (
                    "A brief, natural farewell in the conversation's current language. "
                    "No questions or promises of further conversation. "
                    "Use an empty string to use the configured farewell."
                ),
            },
        },
        required=["goodbye"],
        handler=handler,
    )
