"""Interruption bookkeeping: history must record what was heard, not what was written."""

from __future__ import annotations

# Exercise the real output queue and assistant aggregation, including the HTTP
# TTS frame order (source text, start, audio, delivered text, stop).
import asyncio

from pipecat.frames.frames import (
    AggregatedTextFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from pipecat.utils.text.base_text_aggregator import AggregationType

from src.application.engine.context.interruption import (
    INTERRUPTION_MARKER,
    SpokenAssistantAggregator,
    SpokenSegment,
    SpokenTextTracker,
    truncate_to_bytes,
)


def segments(*pairs: tuple[str, int]) -> list[SpokenSegment]:
    """Build segments from (text, byte_length) pairs, laid out contiguously."""
    out: list[SpokenSegment] = []
    cursor = 0
    for text, length in pairs:
        out.append(
            SpokenSegment(text=text, start_byte=cursor, end_byte=cursor + length)
        )
        cursor += length
    return out


def test_nothing_played_drops_everything():
    spoken, dropped = truncate_to_bytes(segments(("Hello there.", 100)), played_bytes=0)
    assert spoken == ""
    assert dropped == "Hello there."


def test_everything_played_keeps_everything():
    segs = segments(("Hello there.", 100), ("How can I help?", 120))
    spoken, dropped = truncate_to_bytes(segs, played_bytes=220)
    assert spoken == "Hello there. How can I help?"
    assert dropped == ""


def test_cut_on_a_segment_boundary():
    segs = segments(
        ("Your order shipped Tuesday.", 100), ("I can email the tracking.", 100)
    )
    spoken, dropped = truncate_to_bytes(segs, played_bytes=100)

    assert spoken == "Your order shipped Tuesday."
    assert dropped == "I can email the tracking."


def test_cut_mid_segment_falls_back_to_a_word_boundary():
    """A half-spoken word in history reads as a transcription bug two turns later."""
    segs = segments(("Your order shipped on Tuesday", 290))
    spoken, dropped = truncate_to_bytes(segs, played_bytes=150)

    assert spoken
    assert dropped
    assert (spoken + dropped).replace(" ", "") == "Yourordershippedon Tuesday".replace(
        " ", ""
    )
    # Neither side ends or starts mid-word.
    assert not spoken.endswith(("Tu", "Tues", "shipp"))
    for word in spoken.split():
        assert word in ["Your", "order", "shipped", "on", "Tuesday"]


def test_the_dropped_text_is_the_exact_remainder():
    segs = segments(("one two three four five six seven eight", 400))
    spoken, dropped = truncate_to_bytes(segs, played_bytes=200)

    recombined = f"{spoken} {dropped}".split()
    assert recombined == [
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
    ]


def test_a_short_first_segment_is_not_lost():
    segs = segments(("Sure.", 20), ("Let me look that up for you.", 200))
    spoken, dropped = truncate_to_bytes(segs, played_bytes=20)

    assert spoken == "Sure."
    assert dropped == "Let me look that up for you."


class PacedOutput(BaseOutputTransport):
    def __init__(self, sample_rate=16000):
        super().__init__(
            TransportParams(
                audio_out_enabled=True,
                audio_out_sample_rate=sample_rate,
                audio_out_10ms_chunks=2,
                audio_out_end_silence_secs=0,
            )
        )

    async def start(self, frame):
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def write_audio_frame(self, frame):
        await asyncio.sleep(
            len(frame.audio) / (frame.sample_rate * frame.num_channels * 2)
        )
        return True


def clip(text, context_id, seconds, *, sample_rate=16000, complete=True, save=True):
    anchor = AggregatedTextFrame(text, AggregationType.SENTENCE, context_id=context_id)
    anchor.will_be_spoken = True
    anchor.append_to_context = False
    frames = [
        anchor,
        TTSStartedFrame(context_id=context_id, append_to_context=save),
        TTSAudioRawFrame(
            b"\x10\x00" * round(sample_rate * seconds),
            sample_rate,
            1,
            context_id=context_id,
        ),
    ]
    if complete:
        text_frame = TTSTextFrame(text, AggregationType.SENTENCE, context_id=context_id)
        text_frame.append_to_context = save
        frames += [text_frame, TTSStoppedFrame(context_id=context_id)]
    return frames


async def speak(frames, *, initial=None, estimate=True, buffer_seconds=0.04, tts=None):
    context = LLMContext(initial or [])
    tracker = SpokenTextTracker()
    assistant = SpokenAssistantAggregator(
        context,
        tracker=tracker,
        estimate_partial_text=estimate,
        output_buffer_secs=buffer_seconds,
    )
    events = []

    @assistant.event_handler("on_assistant_turn_stopped")
    async def on_stopped(_, message):
        events.append(message)

    await run_test(
        Pipeline([*([tts] if tts else []), tracker, PacedOutput(), assistant]),
        frames_to_send=frames,
    )
    return context.messages, events, tracker


async def test_interruption_saves_partial_http_clip_and_public_event():
    messages, events, tracker = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip("one two three four five six seven eight", "a", 0.5),
            SleepFrame(0.22),
            InterruptionFrame(),
            SleepFrame(0.06),
        ]
    )
    assert len(messages) == 1
    assert messages[0]["content"].startswith("one two")
    assert "eight" not in messages[0]["content"]
    assert messages[0]["content"].endswith(INTERRUPTION_MARKER)
    assert events[-1].content == messages[0]["content"]
    assert events[-1].interrupted
    assert not tracker._contexts


async def test_multiple_clips_keep_earlier_spoken_sentences():
    messages, _, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip("Your order shipped Tuesday.", "a", 0.1),
            *clip("I can also email you the tracking number.", "b", 0.5),
            SleepFrame(0.3),
            InterruptionFrame(),
            SleepFrame(0.06),
        ]
    )
    assert messages[0]["content"].startswith("Your order shipped Tuesday. I")
    assert "tracking number" not in messages[0]["content"]
    assert messages[0]["content"].endswith(INTERRUPTION_MARKER)


async def test_uninterrupted_response_is_unchanged():
    messages, events, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip("Hello caller.", "a", 0.1),
            *clip("How can I help?", "b", 0.1),
            LLMFullResponseEndFrame(),
            SleepFrame(0.3),
        ]
    )
    assert messages == [
        {"role": "assistant", "content": "Hello caller. How can I help?"}
    ]
    assert events[-1].content == messages[0]["content"]
    assert not events[-1].interrupted


async def test_interruption_before_audio_never_overwrites_previous_reply_or_tool_calls():
    old = [
        {"role": "assistant", "content": "Earlier answer"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "sms",
                    "type": "function",
                    "function": {"name": "send_sms", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "sms", "content": "SMS sent"},
        {"role": "user", "content": "Something else"},
    ]
    messages, _, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            SleepFrame(0.02),
            InterruptionFrame(),
            SleepFrame(0.03),
        ],
        initial=[dict(m) for m in old],
    )
    assert messages == old


async def test_incomplete_synthesis_is_not_extrapolated_as_a_complete_clip():
    messages, _, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip("one two three four five six seven eight", "a", 0.1, complete=False),
            SleepFrame(0.14),
            InterruptionFrame(),
            SleepFrame(0.03),
        ]
    )
    assert messages == [{"role": "assistant", "content": INTERRUPTION_MARKER.strip()}]


async def test_output_resampling_does_not_change_fraction_of_spoken_text():
    messages, _, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip(
                "one two three four five six seven eight", "a", 0.5, sample_rate=24000
            ),
            SleepFrame(0.22),
            InterruptionFrame(),
            SleepFrame(0.05),
        ]
    )
    assert messages[0]["content"].startswith("one two")
    assert "seven" not in messages[0]["content"]


async def test_playback_gap_is_not_counted_as_spoken_audio():
    messages, _, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip("First sentence.", "a", 0.08),
            SleepFrame(0.35),
            *clip("one two three four five six seven eight", "b", 0.5),
            SleepFrame(0.16),
            InterruptionFrame(),
            SleepFrame(0.04),
        ]
    )
    assert messages[0]["content"].startswith("First sentence. one")
    assert "seven" not in messages[0]["content"]


async def test_streaming_provider_keeps_only_delivered_word_text():
    text = TTSTextFrame("one two", AggregationType.WORD, context_id="a")
    text.includes_inter_frame_spaces = True
    messages, _, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip("one two three four five", "a", 0.08, complete=False),
            text,
            SleepFrame(0.15),
            InterruptionFrame(),
            SleepFrame(0.04),
        ],
        estimate=False,
    )
    assert messages == [
        {"role": "assistant", "content": "one two" + INTERRUPTION_MARKER}
    ]


async def test_audio_excluded_from_context_stays_excluded_on_interruption():
    messages, _, _ = await speak(
        [
            *clip("Do not save this prompt.", "a", 0.5, save=False),
            SleepFrame(0.16),
            InterruptionFrame(),
            SleepFrame(0.04),
        ]
    )
    assert messages == []


async def test_second_response_does_not_inherit_first_response_audio():
    messages, _, _ = await speak(
        [
            LLMFullResponseStartFrame(),
            *clip("First answer.", "a", 0.08),
            LLMFullResponseEndFrame(),
            SleepFrame(0.16),
            LLMFullResponseStartFrame(),
            *clip("one two three four five six seven eight", "b", 0.5),
            SleepFrame(0.18),
            InterruptionFrame(),
            SleepFrame(0.04),
        ]
    )
    assert messages[0] == {"role": "assistant", "content": "First answer."}
    assert messages[1]["content"].startswith("one")
    assert "seven" not in messages[1]["content"]


async def test_real_http_tts_reuses_context_across_multiple_clips():
    from pipecat.services.openai.tts import OpenAITTSSettings

    from src.integrations.tts.qwen3_tts import Qwen3TTSService

    class LocalTTS(Qwen3TTSService):
        def __init__(self):
            super().__init__(
                api_key="test",
                settings=OpenAITTSSettings(model="test", voice="test"),
            )
            self.requests = []

        async def run_tts(self, text, context_id):
            self.requests.append((text, context_id))
            seconds = 0.1 if len(self.requests) == 1 else 0.5
            yield TTSAudioRawFrame(
                b"\x10\x00" * round(self.sample_rate * seconds),
                self.sample_rate,
                1,
                context_id=context_id,
            )

    tts = LocalTTS()
    try:
        messages, _, _ = await speak(
            [
                LLMFullResponseStartFrame(),
                LLMTextFrame(
                    "Your order shipped Tuesday. I can also email you the tracking number."
                ),
                LLMFullResponseEndFrame(),
                SleepFrame(0.3),
                InterruptionFrame(),
                SleepFrame(0.06),
            ],
            tts=tts,
        )
    finally:
        await tts._client.close()
    assert len(tts.requests) == 2
    assert tts.requests[0][1] == tts.requests[1][1]
    assert messages[0]["content"].startswith("Your order shipped Tuesday. I")
    assert "tracking number" not in messages[0]["content"]
    assert messages[0]["content"].endswith(INTERRUPTION_MARKER)
