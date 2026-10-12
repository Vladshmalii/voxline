"""Synthetic, reproducible time-to-first-audio (TTFA) benchmark.

Exercises the real production chunking aggregators (:mod:`chunking`) against a
simulated LLM token stream and a TTS latency model calibrated from the
Qwen3-TTS measurements already documented in ``chunking.py``'s module
docstring (time-to-first-byte tracks input length: 0.7 s for 4 words, 1.4 s
for 13, 3.8 s for 37).

No real STT/LLM/TTS/telephony is involved — only the two things that decide
TTFA: which text reaches the wire first (the aggregator under test,
unmodified production code) and how long that text takes the deployed TTS to
speak first (calibrated from the project's own field notes). Absolute
milliseconds are indicative, not a production SLA; the number that matters is
the naive-vs-chunked gap, since both scenarios share the same TTS model and
generation rate.

Run ``python -m src.application.engine.latency_benchmark`` for a printed
report, or import :func:`compare` directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from src.application.engine.chunking import ClauseAggregator, WholeTurnAggregator

#: (word_count, time-to-first-byte seconds) anchors measured against the
#: deployed Qwen3-TTS — see chunking.py's module docstring. Piecewise-linear
#: interpolation between them; the last segment's slope extrapolates beyond.
_TTS_TTFB_ANCHORS: tuple[tuple[int, float], ...] = ((4, 0.7), (13, 1.4), (37, 3.8))

#: Assumed LLM streaming rate — a documented *synthetic* input, not a
#: production measurement. ~22 tok/s is a typical middle-of-the-road rate for
#: a hosted 7-14B model; rerun with a different value to see how the gap
#: scales with generation speed.
DEFAULT_TOKEN_INTERVAL_S: float = 0.045

#: A representative multi-sentence agent reply (43 words), the shape of
#: reply that actually appears on calls — long enough that "wait for the
#: whole thing" is a real cost, not a rounding error.
SAMPLE_REPLY: str = (
    "I can certainly help you with that order, and I will also check whether "
    "the refund has already been processed. Could you confirm the last four "
    "digits of the card you used, so I can pull up the transaction and give "
    "you an exact answer?"
)


def tts_ttfb_seconds(word_count: int) -> float:
    """Time-to-first-byte for a Qwen3-TTS request of ``word_count`` words.

    Piecewise-linear interpolation over :data:`_TTS_TTFB_ANCHORS`;
    extrapolates past the last anchor using its slope.
    """
    anchors = _TTS_TTFB_ANCHORS
    for (w0, t0), (w1, t1) in pairwise(anchors):
        if word_count <= w1:
            break
    else:
        (w0, t0), (w1, t1) = anchors[-2], anchors[-1]
    slope = (t1 - t0) / (w1 - w0)
    return max(0.05, t0 + slope * (word_count - w0))


def _word_count(text: str) -> int:
    return len(text.split())


@dataclass(frozen=True)
class TurnLatencyResult:
    """One strategy's simulated time-to-first-audio for one reply."""

    strategy: str
    first_chunk_text: str
    generation_to_first_chunk_s: float
    tts_ttfb_s: float

    @property
    def first_chunk_words(self) -> int:
        return _word_count(self.first_chunk_text)

    @property
    def time_to_first_audio_s(self) -> float:
        return self.generation_to_first_chunk_s + self.tts_ttfb_s


async def _simulate(
    aggregator: ClauseAggregator | WholeTurnAggregator,
    text: str,
    *,
    token_interval_s: float,
) -> TurnLatencyResult:
    """Stream ``text`` through ``aggregator`` one word at a time, on a clock.

    Mirrors ``tests/engine/test_chunking.py``'s ``feed``/``feed_turn`` helpers,
    plus a wall-clock so the first emitted chunk carries a timestamp.
    """
    elapsed = 0.0
    first_chunk: str | None = None
    first_chunk_at: float | None = None

    for word in text.split(" "):
        elapsed += token_interval_s
        async for aggregation in aggregator.aggregate(word + " "):
            if first_chunk is None:
                first_chunk, first_chunk_at = aggregation.text, elapsed

    if first_chunk is None:
        tail = await aggregator.flush()
        if tail is not None:
            first_chunk, first_chunk_at = tail.text, elapsed

    assert first_chunk is not None and first_chunk_at is not None, (
        "aggregator produced nothing for a non-empty reply"
    )
    return TurnLatencyResult(
        strategy=type(aggregator).__name__,
        first_chunk_text=first_chunk,
        generation_to_first_chunk_s=first_chunk_at,
        tts_ttfb_s=tts_ttfb_seconds(_word_count(first_chunk)),
    )


async def compare(
    text: str = SAMPLE_REPLY,
    *,
    token_interval_s: float = DEFAULT_TOKEN_INTERVAL_S,
    min_words: int = 8,
) -> tuple[TurnLatencyResult, TurnLatencyResult]:
    """Run the naive (before) and chunked (after) strategies over the same reply.

    Returns:
        ``(naive, chunked)`` — ``WholeTurnAggregator`` vs. ``ClauseAggregator``,
        the same pair ``TTS_CHUNKING=0`` toggles between in production.
    """
    naive = await _simulate(
        WholeTurnAggregator(), text, token_interval_s=token_interval_s
    )
    chunked = await _simulate(
        ClauseAggregator(min_words=min_words), text, token_interval_s=token_interval_s
    )
    return naive, chunked


def render_report(naive: TurnLatencyResult, chunked: TurnLatencyResult) -> str:
    """Render a before/after time-to-first-audio report."""
    saved_ms = round(
        (naive.time_to_first_audio_s - chunked.time_to_first_audio_s) * 1000
    )
    saved_pct = round(100 * saved_ms / (naive.time_to_first_audio_s * 1000))
    return (
        "synthetic TTFA benchmark (no live STT/LLM/TTS/telephony — see\n"
        "latency_benchmark.py module docstring for method and caveats)\n"
        "\n"
        f"BEFORE — {naive.strategy} (TTS_CHUNKING=0, whole reply as one request):\n"
        f"  generation→first chunk : {naive.generation_to_first_chunk_s * 1000:.0f} ms "
        f"({naive.first_chunk_words} words)\n"
        f"  TTS time-to-first-byte : {naive.tts_ttfb_s * 1000:.0f} ms\n"
        f"  time to first audio    : {naive.time_to_first_audio_s * 1000:.0f} ms\n"
        "\n"
        f"AFTER — {chunked.strategy} (production default):\n"
        f"  generation→first chunk : {chunked.generation_to_first_chunk_s * 1000:.0f} ms "
        f"({chunked.first_chunk_words} words)\n"
        f"  TTS time-to-first-byte : {chunked.tts_ttfb_s * 1000:.0f} ms\n"
        f"  time to first audio    : {chunked.time_to_first_audio_s * 1000:.0f} ms\n"
        "\n"
        f"TTFA reduced by {saved_ms} ms ({saved_pct}%) on this sample reply.\n"
    )


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        naive, chunked = await compare()
        print(render_report(naive, chunked))

    asyncio.run(_main())
