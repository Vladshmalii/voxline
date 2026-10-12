"""Captions: transcript text mirrored to the wire as transport messages.

The transcript frames themselves never reach a browser — the user aggregator
consumes them, and the output transport hands its serializer only audio,
control, and transport messages — so these tests pin the tap that mints the
messages the transport does deliver.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    OutputTransportMessageUrgentFrame,
    TextFrame,
    TranscriptionFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.ui_events import AgentStateTap, CaptionTap, caption_for


def user_frame(text: str, *, final: bool) -> Frame:
    cls = TranscriptionFrame if final else InterimTranscriptionFrame
    return cls(text, "user-1", "2026-08-31T00:00:00Z", None)


def test_final_user_transcript_is_a_final_user_caption():
    assert caption_for(user_frame("да, слушаю", final=True)) == {
        "event": "transcript",
        "role": "user",
        "text": "да, слушаю",
        "final": True,
    }


def test_interim_user_transcript_is_a_revisable_caption():
    caption = caption_for(user_frame("да, слу", final=False))
    assert caption is not None
    assert (caption["role"], caption["final"]) == ("user", False)


def test_spoken_agent_text_is_an_assistant_caption():
    caption = caption_for(TTSTextFrame(text="Здравствуйте!", aggregated_by="word"))
    assert caption == {
        "event": "transcript",
        "role": "assistant",
        "text": "Здравствуйте!",
        "final": True,
    }


def test_frames_without_a_caption_yield_none():
    # A plain TextFrame is the LLM's output on its way to TTS — captioning it
    # would show text the interruption bookkeeping may later prove unspoken.
    assert caption_for(TextFrame("not spoken yet")) is None


def build_tap() -> tuple[CaptionTap, list[tuple[Frame, FrameDirection]]]:
    tap = CaptionTap()
    pushed: list[tuple[Frame, FrameDirection]] = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append((frame, direction))

    tap.push_frame = collect  # type: ignore[method-assign]
    return tap, pushed


async def test_the_tap_mints_a_message_and_still_forwards_the_frame():
    tap, pushed = build_tap()
    frame = user_frame("hello", final=True)

    await tap.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert [type(f) for f, _ in pushed] == [
        OutputTransportMessageUrgentFrame,
        type(frame),
    ]
    assert pushed[0][0].message["text"] == "hello"
    # The original frame travels on, in its original direction.
    assert pushed[1] == (frame, FrameDirection.DOWNSTREAM)


async def test_upstream_traffic_passes_untouched():
    """The after-stt tap sits on the recogniser's settings-update path."""
    tap, pushed = build_tap()
    frame = TextFrame("anything")

    await tap.process_frame(frame, FrameDirection.UPSTREAM)

    assert pushed == [(frame, FrameDirection.UPSTREAM)]


async def test_captionless_frames_pass_without_a_message():
    tap, pushed = build_tap()
    frame = TextFrame("llm output")

    await tap.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert pushed == [(frame, FrameDirection.DOWNSTREAM)]


# ---------------------------------------------------------------------------
# Agent state narration
# ---------------------------------------------------------------------------

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    LLMFullResponseStartFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)


def events_for(tap: AgentStateTap, *frames: Frame) -> list[dict]:
    out: list[dict] = []
    for frame in frames:
        out.extend(tap._events(frame))
    return out


def test_a_greeting_narrates_thinking_then_speaking_then_listening():
    """The kickoff runs the LLM with no user turn before it."""
    tap = AgentStateTap()

    events = events_for(
        tap,
        LLMFullResponseStartFrame(),
        BotStartedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
    )

    assert [e["state"] for e in events] == ["thinking", "speaking", "listening"]


def test_a_normal_turn_walks_the_full_cycle():
    tap = AgentStateTap()

    events = events_for(
        tap,
        UserStartedSpeakingFrame(),
        UserStoppedSpeakingFrame(),
        LLMFullResponseStartFrame(),
        BotStartedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
    )

    assert [e["state"] for e in events] == [
        "user_speaking",
        "listening",
        "thinking",
        "speaking",
        "listening",
    ]


def test_barging_in_mid_speech_reports_the_interruption():
    tap = AgentStateTap()
    events_for(tap, LLMFullResponseStartFrame(), BotStartedSpeakingFrame())

    events = events_for(tap, UserStartedSpeakingFrame())

    assert events == [
        {"event": "interruption", "while": "speaking"},
        {"event": "state", "state": "user_speaking"},
    ]


def test_barging_in_while_the_model_is_still_generating_names_thinking():
    tap = AgentStateTap()
    events_for(tap, LLMFullResponseStartFrame())

    events = events_for(tap, UserStartedSpeakingFrame())

    assert events[0] == {"event": "interruption", "while": "thinking"}


def test_speaking_after_the_agent_finished_is_no_interruption():
    tap = AgentStateTap()
    events_for(
        tap,
        LLMFullResponseStartFrame(),
        BotStartedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
    )

    events = events_for(tap, UserStartedSpeakingFrame())

    assert events == [{"event": "state", "state": "user_speaking"}]


def test_repeated_signals_do_not_repeat_the_state():
    tap = AgentStateTap()

    events = events_for(tap, BotStoppedSpeakingFrame(), BotStoppedSpeakingFrame())

    assert events == []  # already listening, twice over


async def test_the_tap_forwards_the_frame_and_sends_the_event():
    tap = AgentStateTap()
    pushed: list[Frame] = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    tap.push_frame = collect  # type: ignore[method-assign]
    frame = LLMFullResponseStartFrame()

    await tap.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert pushed[0] is frame  # the pipeline sees the frame before the UI does
    assert [type(f) for f in pushed[1:]] == [OutputTransportMessageUrgentFrame]
    assert pushed[1].message == {"event": "state", "state": "thinking"}


async def test_the_emitter_lends_its_position_to_outside_events():
    from src.application.engine.ui_events import UiEventEmitter

    emitter = UiEventEmitter()
    pushed: list[Frame] = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    emitter.push_frame = collect  # type: ignore[method-assign]

    await emitter.emit({"event": "timing", "turn": 1})
    frame = TextFrame("passing through")
    await emitter.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert isinstance(pushed[0], OutputTransportMessageUrgentFrame)
    assert pushed[0].message == {"event": "timing", "turn": 1}
    assert pushed[1] is frame
