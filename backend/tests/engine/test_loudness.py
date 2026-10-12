"""Chunk loudness matching: the level half of "it sounds like two people"."""

from __future__ import annotations

import math
import struct

import audioop

from src.application.engine.loudness import SILENCE_FLOOR, ChunkLoudnessMatcher

RATE = 24000


def tone(rms: int, seconds: float = 0.5, freq: int = 220) -> bytes:
    """A sine at a requested RMS, as PCM16."""
    amplitude = rms * math.sqrt(2)
    count = int(RATE * seconds)
    return struct.pack(
        f"<{count}h",
        *(
            int(
                max(
                    -32768,
                    min(32767, amplitude * math.sin(2 * math.pi * freq * i / RATE)),
                )
            )
            for i in range(count)
        ),
    )


def rms(pcm: bytes) -> int:
    return audioop.rms(pcm, 2)


def test_the_first_chunk_is_never_touched():
    """It is on the path to first audio, and it defines the reference."""
    matcher = ChunkLoudnessMatcher()
    first = tone(3000)

    assert matcher.match(first) is first
    assert matcher.reference is not None


def test_a_later_quiet_chunk_is_brought_up_to_the_first():
    matcher = ChunkLoudnessMatcher()
    matcher.observe(tone(4000))

    matched = matcher.match(tone(2000))

    assert abs(rms(matched) - 4000) < 200


def test_a_later_loud_chunk_is_brought_down():
    matcher = ChunkLoudnessMatcher()
    matcher.observe(tone(2000))

    matched = matcher.match(tone(4000))

    assert abs(rms(matched) - 2000) < 200


def test_the_correction_is_capped():
    """A chunk 10x quieter is a different failure; do not amplify it into noise."""
    matcher = ChunkLoudnessMatcher(max_gain=2.0)
    matcher.observe(tone(8000))

    matched = matcher.match(tone(800))

    assert rms(matched) <= 800 * 2.0 + 100


def test_silence_is_neither_a_reference_nor_corrected():
    matcher = ChunkLoudnessMatcher()
    quiet = tone(SILENCE_FLOOR // 2)

    assert matcher.match(quiet) is quiet
    assert matcher.reference is None
    # And the next real chunk becomes the reference instead.
    matcher.match(tone(3000))
    assert matcher.reference is not None


def test_an_inaudible_correction_is_skipped():
    """Under half a dB, return the buffer untouched rather than rewrite it."""
    matcher = ChunkLoudnessMatcher()
    matcher.observe(tone(3000))
    close = tone(3050)

    assert matcher.match(close) is close


def test_scaling_never_clips():
    matcher = ChunkLoudnessMatcher()
    matcher.observe(tone(20000))
    # Peaks near full scale already; the gain must give way to the ceiling.
    loud = tone(18000)

    matched = matcher.match(loud)

    assert audioop.max(matched, 2) <= 32767
