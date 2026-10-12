"""Track generated TTS before output and save heard text after paced output.

Pipecat 1.7 consumes TTSTextFrame in its assistant aggregator. HTTP TTS emits
that text *after* the clip, while AggregatedTextFrame carries the source text
before synthesis. The two pipeline positions share context IDs, not a wall
clock: pauses between clips must never count as played audio.

For completed HTTP clips, partial text is estimated proportionally to audio
actually written by the output transport, rounded down to a whole word. This
is still an estimate (speech is not uniform, and remote playout is not acked).
An incomplete clip is not extrapolated. Timestamped/streaming providers retain
Pipecat's delivered text instead. History is corrected before it is saved, so
old assistant messages and tool calls cannot be overwritten accidentally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from pipecat.frames.frames import (
    AggregatedTextFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.aggregators.llm_response_universal import LLMAssistantAggregator
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.string import TextPartForConcatenation

DEFAULT_OUTPUT_BUFFER_SECS: Final[float] = 0.04
INTERRUPTION_MARKER: Final[str] = " [interrupted by caller]"


@dataclass
class SpokenSegment:
    text: str
    start_byte: int
    end_byte: int = 0

    @property
    def byte_length(self) -> int:
        return max(0, self.end_byte - self.start_byte)


@dataclass
class _Synthesis:
    text: str = ""
    audio_seconds: float = 0.0
    complete: bool = False
    append_to_context: bool = True


@dataclass
class _Playback:
    context_id: str
    synthesis: _Synthesis
    audio_seconds: float = 0.0
    delivered_text: list[str] = field(default_factory=list)


def truncate_to_bytes(
    segments: list[SpokenSegment], played_bytes: int
) -> tuple[str, str]:
    """Split recorded segments into heard and unheard text at a byte offset.

    Pure, so the arithmetic is unit-testable without a pipeline. Within the
    segment that was cut mid-way, the split is proportional to the audio and then
    snapped back to a word boundary — half a word helps nobody, and an agent that
    "said" a partial word reads as a transcription bug later.

    Args:
        segments: Segments in production order, with byte ranges filled in.
        played_bytes: Audio bytes actually delivered.

    Returns:
        ``(spoken, dropped)`` text.
    """
    spoken_parts: list[str] = []
    dropped_parts: list[str] = []

    for segment in segments:
        if segment.end_byte <= played_bytes:
            spoken_parts.append(segment.text)
            continue
        if segment.start_byte >= played_bytes:
            dropped_parts.append(segment.text)
            continue

        # Straddles the cut.
        length = segment.byte_length
        fraction = (played_bytes - segment.start_byte) / length if length else 0.0
        split = int(len(segment.text) * max(0.0, min(1.0, fraction)))
        head, tail = segment.text[:split], segment.text[split:]
        if tail and not tail[0].isspace():
            boundary = head.rfind(" ")
            if boundary >= 0:
                head, tail = head[:boundary], head[boundary:] + tail
            else:
                head, tail = "", segment.text
        if head.strip():
            spoken_parts.append(head)
        if tail.strip():
            dropped_parts.append(tail)

    return _join(spoken_parts), _join(dropped_parts)


def _join(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p.strip()).strip()


class SpokenTextTracker(FrameProcessor):
    """Collect synthesis metadata immediately before transport.output()."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._contexts: dict[str, _Synthesis] = {}
        self._segments: dict[int, _Synthesis] = {}
        self._context_append: dict[str, bool] = {}

    def get(self, context_id: str) -> _Synthesis:
        return self._contexts.setdefault(context_id, _Synthesis())

    def release(self, context_id: str) -> None:
        self._contexts.pop(context_id, None)
        self._context_append.pop(context_id, None)

    def take_segment(self, frame: AggregatedTextFrame) -> _Synthesis:
        return self._segments.pop(frame.id, _Synthesis())

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            context_id = getattr(frame, "context_id", None)
            if isinstance(frame, (InterruptionFrame, EndFrame, CancelFrame)):
                # The assistant holds references to any contexts already being
                # played. Clearing the lookup also discards queued, unplayed clips.
                self._contexts.clear()
                self._segments.clear()
                self._context_append.clear()
            elif context_id:
                if (
                    isinstance(frame, AggregatedTextFrame)
                    and not isinstance(frame, TTSTextFrame)
                    and frame.will_be_spoken
                ):
                    # HTTP TTS can reuse ONE context ID for several requests.
                    # Each source frame is its own clip, with its own duration.
                    segment = _Synthesis(
                        text=frame.text,
                        append_to_context=self._context_append.get(context_id, True),
                    )
                    self._contexts[context_id] = segment
                    self._segments[frame.id] = segment
                else:
                    segment = self.get(context_id)
                if isinstance(frame, TTSTextFrame):
                    # HTTP services place the full original text after all audio.
                    if frame.text == segment.text:
                        segment.complete = True
                elif isinstance(frame, TTSStartedFrame):
                    segment.append_to_context = frame.append_to_context
                    self._context_append[context_id] = frame.append_to_context
                elif isinstance(frame, TTSAudioRawFrame):
                    segment.audio_seconds += len(frame.audio) / (
                        frame.sample_rate * frame.num_channels * 2
                    )
                elif isinstance(frame, TTSStoppedFrame):
                    segment.complete = True
        await self.push_frame(frame, direction)


class SpokenAssistantAggregator(LLMAssistantAggregator):
    """Persist heard text using the output transport's delivered audio frames.

    Install after transport.output(), sharing the tracker before it. This
    class customizes Pipecat 1.7's aggregation buffer only for interruptions;
    its normal context writes, tool handling and public events stay intact.
    """

    def __init__(
        self,
        context,
        *,
        tracker: SpokenTextTracker,
        estimate_partial_text: bool = False,
        output_buffer_secs: float = DEFAULT_OUTPUT_BUFFER_SECS,
        **kwargs,
    ):
        super().__init__(context, **kwargs)
        self._tracker = tracker
        self._estimate_partial_text = estimate_partial_text
        self._output_buffer_secs = output_buffer_secs
        self._playbacks: list[_Playback] = []
        self._playing: _Playback | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if direction == FrameDirection.DOWNSTREAM:
            if (
                isinstance(frame, AggregatedTextFrame)
                and not isinstance(frame, TTSTextFrame)
                and frame.will_be_spoken
                and frame.context_id
            ):
                self._playing = _Playback(
                    frame.context_id, self._tracker.take_segment(frame)
                )
                self._playbacks.append(self._playing)
            elif isinstance(frame, TTSStartedFrame) and frame.context_id:
                if (
                    self._playing is None
                    or self._playing.context_id != frame.context_id
                ):
                    self._playing = _Playback(
                        frame.context_id, self._tracker.get(frame.context_id)
                    )
                    self._playbacks.append(self._playing)
                self._playing.synthesis.append_to_context = frame.append_to_context
            elif isinstance(frame, TTSAudioRawFrame) and self._playing is not None:
                self._playing.audio_seconds += len(frame.audio) / (
                    frame.sample_rate * frame.num_channels * 2
                )
            elif isinstance(frame, TTSTextFrame) and self._playing is not None:
                if frame.append_to_context:
                    self._playing.delivered_text.append(frame.text)
            elif isinstance(frame, TTSStoppedFrame) and frame.context_id:
                self._tracker.release(frame.context_id)
        await super().process_frame(frame, direction)

    def _heard_text(self) -> str:
        if not self._estimate_partial_text:
            return self.aggregation_string()
        parts = []
        for playback in self._playbacks:
            segment = playback.synthesis
            if not segment.append_to_context:
                continue
            if playback.delivered_text:
                parts.append(_join(playback.delivered_text))
            elif segment.complete and segment.audio_seconds > 0:
                # Use per-context durations so source/output sample rates may
                # differ and gaps between chunks cannot inflate the estimate.
                total = max(1, round(segment.audio_seconds * 1_000_000))
                played = max(
                    0,
                    round(
                        (playback.audio_seconds - self._output_buffer_secs) * 1_000_000
                    ),
                )
                spoken, _ = truncate_to_bytes(
                    [SpokenSegment(segment.text, 0, total)], played
                )
                parts.append(spoken)
        return _join(parts)

    async def _handle_interruptions(self, frame: InterruptionFrame):
        # Only modify this response's pending buffer; never search backwards in
        # shared history (which may end with an earlier answer or a tool call).
        if self._assistant_turn_start_timestamp:
            text = self._heard_text()
            heard_audio = any(
                p.audio_seconds > 0 and p.synthesis.append_to_context
                for p in self._playbacks
            )
            if text or heard_audio:
                text = f"{text}{INTERRUPTION_MARKER}".strip()
            self._aggregation = (
                [TextPartForConcatenation(text, includes_inter_part_spaces=True)]
                if text
                else []
            )
        await super()._handle_interruptions(frame)

    async def _trigger_assistant_turn_stopped(self, *, interrupted: bool = False):
        await super()._trigger_assistant_turn_stopped(interrupted=interrupted)
        self._playbacks.clear()
        self._playing = None
