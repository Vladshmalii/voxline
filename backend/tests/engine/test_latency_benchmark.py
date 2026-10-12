"""Chunking must keep beating the naive whole-reply baseline for TTFA."""

from __future__ import annotations

from src.application.engine.latency_benchmark import (
    SAMPLE_REPLY,
    compare,
    render_report,
    tts_ttfb_seconds,
)


async def test_chunked_reaches_first_audio_sooner_than_the_naive_baseline():
    naive, chunked = await compare()

    assert chunked.time_to_first_audio_s < naive.time_to_first_audio_s
    assert chunked.first_chunk_words < naive.first_chunk_words


async def test_naive_speaks_the_entire_reply_in_one_request():
    naive, _ = await compare()

    assert naive.first_chunk_text.strip() == SAMPLE_REPLY.strip()


async def test_report_renders_a_before_after_summary():
    naive, chunked = await compare()

    report = render_report(naive, chunked)

    assert "BEFORE" in report
    assert "AFTER" in report
    assert "TTFA reduced by" in report


def test_tts_ttfb_matches_the_documented_anchors():
    assert tts_ttfb_seconds(4) == 0.7
    assert tts_ttfb_seconds(13) == 1.4
    assert tts_ttfb_seconds(37) == 3.8
    assert tts_ttfb_seconds(20) < tts_ttfb_seconds(37) < tts_ttfb_seconds(60)
