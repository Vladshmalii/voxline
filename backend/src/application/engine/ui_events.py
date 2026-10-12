"""The playground UI's window into the pipeline: captions and agent state.

A browser playground wants to *show* what is happening — the words being said
and what the agent is doing right now — but the frames that carry that never
reach the wire on their own: the user aggregator consumes
``TranscriptionFrame``/``InterimTranscriptionFrame`` rather than forwarding
them, and the output transport hands its serializer only audio, control, and
transport-message frames. So UI events ride
``OutputTransportMessageUrgentFrame`` — minted here by taps spliced into the
pipeline via :class:`~src.application.engine.pipeline.PipelineTaps`
(``after_stt`` for the caller's transcripts, ``before_output`` for everything
else), and written to the wire by the transport's serializer.

Urgent rather than queued on purpose: a queued transport message is dropped
along with the buffered audio when the caller barges in, and the events of the
barge-in itself must survive it.

A phone leg never sees any of this — the taps exist only where a UI transport
splices them in.

Wire envelopes minted here:

* ``{"event": "transcript", "role": "user"|"assistant", "text": …,
  "final": …}`` — live captions (:class:`CaptionTap`);
* ``{"event": "state", "state": "listening"|"user_speaking"|"thinking"|
  "speaking"}`` — what the agent is doing (:class:`AgentStateTap`);
* ``{"event": "interruption", "while": "thinking"|"speaking"}`` — the caller
  started speaking before the agent finished (:class:`AgentStateTap`);
* ``{"event": "tool_call", "name": …, "arguments": …, "result": …}`` — a tool
  (``send_sms``, ``end_call``, …) the agent just called, once it has actually
  run (:class:`ToolCallTap`, VOAD-58) — the UI turns this into a friendly
  line ("Sent an SMS: …") instead of showing raw JSON.

Events minted *outside* the pipeline (the latency observer's per-turn timings)
enter the wire through :class:`UiEventEmitter`, a tap whose only job is to
lend its pipeline position to code that has none.
"""

from __future__ import annotations

from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    FunctionCallResultFrame,
    InterimTranscriptionFrame,
    LLMFullResponseStartFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    TranscriptionFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def caption_for(frame: Frame) -> dict[str, Any] | None:
    """The caption envelope for one frame, or None for frames that carry none.

    The envelope is the playground wire contract's ``transcript`` event:
    ``{"event": "transcript", "role": "user"|"assistant", "text": …,
    "final": …}``. Assistant text is always final — TTS never revises what it
    has already spoken.
    """
    if isinstance(frame, TranscriptionFrame):
        return {
            "event": "transcript",
            "role": "user",
            "text": frame.text,
            "final": True,
        }
    if isinstance(frame, InterimTranscriptionFrame):
        return {
            "event": "transcript",
            "role": "user",
            "text": frame.text,
            "final": False,
        }
    if isinstance(frame, TTSTextFrame):
        return {
            "event": "transcript",
            "role": "assistant",
            "text": frame.text,
            "final": True,
        }
    return None


class CaptionTap(FrameProcessor):
    """Mirror transcript frames to the wire as urgent transport messages.

    Passes every frame through untouched; a caption is an addition, never a
    substitution. Spliced in twice per playground session: after the
    recogniser — the last stop where user transcription frames still exist —
    and before the output transport, where the agent's ``TTSTextFrame``s pass
    on their way out.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Mint a caption when the frame carries one, then forward the frame."""
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            caption = caption_for(frame)
            if caption is not None:
                await self.push_frame(
                    OutputTransportMessageUrgentFrame(message=caption)
                )
        await self.push_frame(frame, direction)


class ToolCallTap(FrameProcessor):
    """Mirror a completed tool call to the wire as a ``tool_call`` event.

    ``FunctionCallResultFrame`` only exists once the handler has actually run
    (see ``pipeline.py``'s ``send_sms`` schema and ``call_end.py``'s
    ``end_call``) — reporting on the *result*, not the LLM's intent to call,
    keeps this from firing for a call the model considered and then didn't
    make. Passes every frame through untouched, same as ``CaptionTap``.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Mint a tool_call event when the frame carries one, then forward it."""
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(
            frame, FunctionCallResultFrame
        ):
            await self.push_frame(
                OutputTransportMessageUrgentFrame(
                    message={
                        "event": "tool_call",
                        "name": frame.function_name,
                        "arguments": frame.arguments,
                        "result": frame.result,
                    }
                )
            )
        await self.push_frame(frame, direction)


class AgentStateTap(FrameProcessor):
    """Narrate what the agent is doing: listening, thinking, speaking.

    One state at a time, emitted only on change, from the signals that all
    pass the ``before_output`` splice point:

    * ``UserStartedSpeakingFrame`` (turn start) → ``user_speaking`` — and when
      it lands while the agent is still ``thinking`` or ``speaking``, an
      ``interruption`` event first, naming what was cut short;
    * ``UserStoppedSpeakingFrame`` (turn commit) → ``listening`` — briefly,
      until the reply's ``LLMFullResponseStartFrame`` flips it to ``thinking``;
    * ``BotStartedSpeakingFrame`` (first audio actually leaving, upstream from
      the transport) → ``speaking``; ``BotStoppedSpeakingFrame`` →
      ``listening``. ``speaking`` deliberately starts at audio-out rather than
      at the TTS request: the caller cares when the voice starts, and the gap
      before it is honestly ``thinking``.

    A silence-handler prompt shows as ``speaking`` with no ``thinking`` before
    it — accurate, since no LLM ran.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Start in ``listening``; the StartFrame announces it to the UI."""
        super().__init__(**kwargs)
        self._state = "listening"

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Forward the frame, then announce whatever state it changed."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        for message in self._events(frame):
            await self.push_frame(OutputTransportMessageUrgentFrame(message=message))

    def _events(self, frame: Frame) -> list[dict[str, Any]]:
        if isinstance(frame, StartFrame):
            # Announce the initial state so the UI never has to assume one.
            return [{"event": "state", "state": self._state}]
        if isinstance(frame, UserStartedSpeakingFrame):
            events = []
            if self._state in ("thinking", "speaking"):
                events.append({"event": "interruption", "while": self._state})
            return events + self._enter("user_speaking")
        if isinstance(frame, UserStoppedSpeakingFrame):
            return self._enter("listening")
        if isinstance(frame, LLMFullResponseStartFrame):
            return self._enter("thinking")
        if isinstance(frame, BotStartedSpeakingFrame):
            return self._enter("speaking")
        if isinstance(frame, BotStoppedSpeakingFrame):
            return self._enter("listening")
        return []

    def _enter(self, state: str) -> list[dict[str, Any]]:
        if state == self._state:
            return []
        self._state = state
        return [{"event": "state", "state": state}]


class UiEventEmitter(FrameProcessor):
    """A pipeline-resident outlet for events minted outside the pipeline.

    The latency observer watches from the task, not from inside the pipeline,
    so it has no way to push a frame; anything holding a reference to this tap
    can. :meth:`emit` is safe to call from any task on the pipeline's loop —
    the same footing the silence handler's timer pushes from. All pipeline
    traffic passes through untouched.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Forward everything; this tap only originates frames via emit()."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    async def emit(self, message: dict[str, Any]) -> None:
        """Send one wire envelope to the UI as an urgent transport message."""
        await self.push_frame(OutputTransportMessageUrgentFrame(message=message))
