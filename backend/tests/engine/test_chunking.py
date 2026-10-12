"""Clause chunking: the LLM→TTS overlap that keeps first audio under a second."""

from __future__ import annotations

from pipecat.utils.text.base_text_aggregator import AggregationType

from src.application.engine.chunking import ClauseAggregator, WholeTurnAggregator


async def feed(
    aggregator: ClauseAggregator, text: str, *, token_size: int = 3
) -> list[str]:
    """Stream text through the aggregator the way an LLM would, and collect chunks."""
    chunks: list[str] = []
    for i in range(0, len(text), token_size):
        async for aggregation in aggregator.aggregate(text[i : i + token_size]):
            chunks.append(aggregation.text)
    return chunks


async def feed_turn(
    aggregator: ClauseAggregator, text: str, *, token_size: int = 3
) -> list[str]:
    """One whole turn: stream the text, then flush the way the service does at
    the end of an LLM response — a final sentence is only confirmed by the
    lookahead that never comes when the text simply stops."""
    chunks = await feed(aggregator, text, token_size=token_size)
    tail = await aggregator.flush()
    if tail:
        chunks.append(tail.text)
    return chunks


async def test_sentence_boundary_always_emits():
    aggregator = ClauseAggregator(min_words=8)
    chunks = await feed(aggregator, "Hello there. How can I help you today? ")

    assert chunks[0] == "Hello there."


async def test_a_long_first_clause_emits_before_the_sentence_ends():
    """The whole point: do not wait for a full stop that is twenty words away."""
    aggregator = ClauseAggregator(min_words=6)
    text = (
        "I can certainly help you with that order, and I will also check "
        "whether the refund has been processed yet."
    )
    chunks = await feed(aggregator, text)

    assert chunks, "nothing was emitted before the sentence ended"
    assert chunks[0].endswith(",")
    assert len(chunks[0].split()) >= 6


async def test_a_clause_boundary_below_min_words_does_not_cut():
    """Cutting after two words produces choppy, unnatural speech."""
    aggregator = ClauseAggregator(min_words=8)
    chunks = await feed(
        aggregator, "Yes, I can help you with that order today, of course. "
    )

    assert all(len(c.split()) >= 3 for c in chunks), chunks


async def test_a_run_on_with_no_punctuation_still_flushes():
    """Without a ceiling, an unpunctuated ramble would stall the whole overlap."""
    aggregator = ClauseAggregator(min_words=5, max_words=10)
    text = " ".join(f"word{i}" for i in range(40)) + " "
    chunks = await feed(aggregator, text)

    assert len(chunks) >= 3
    assert all(len(c.split()) <= 12 for c in chunks), chunks


async def test_words_are_never_split():
    aggregator = ClauseAggregator(min_words=4, max_words=6)
    text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
    chunks = await feed(aggregator, text, token_size=1)

    words = text.split()
    assert " ".join(chunks).split() == words


async def test_emitted_chunks_are_sentence_typed():
    """TTSService only speaks aggregations it recognises as speakable units."""
    aggregator = ClauseAggregator(min_words=3)
    # The trailing "How" is the non-whitespace lookahead the base aggregator
    # needs to confirm the full stop really ended a sentence ("$29." does not).
    types = [a.type for a in await _aggregations(aggregator, "Hello there. How")]

    assert types == [AggregationType.SENTENCE]


async def _aggregations(aggregator: ClauseAggregator, text: str) -> list:
    out = []
    async for aggregation in aggregator.aggregate(text):
        out.append(aggregation)
    return out


async def test_flush_returns_the_tail():
    aggregator = ClauseAggregator(min_words=8)
    await feed(aggregator, "a trailing clause with no terminator")
    remaining = await aggregator.flush()

    assert remaining is not None
    assert "trailing clause" in remaining.text


async def test_interruption_discards_the_buffer():
    aggregator = ClauseAggregator(min_words=8)
    await feed(aggregator, "half a sentence that was")
    await aggregator.handle_interruption()

    assert await aggregator.flush() is None


async def test_max_words_defaults_above_min_words():
    aggregator = ClauseAggregator(min_words=8)
    assert aggregator.max_words > aggregator.min_words


async def test_only_the_first_chunk_of_a_turn_is_cut_at_a_clause():
    """Each request resamples the speaker, so later chunks run to a sentence
    end: full context for the model, and one fewer chance to change voice."""
    aggregator = ClauseAggregator(min_words=6)
    text = (
        "I can certainly help you with that order, and I will check the refund "
        "as well, if that suits you. "
    )
    chunks = await feed_turn(aggregator, text)

    assert chunks[0].endswith(",")
    assert len(chunks) == 2
    # Everything after the first cut arrives as one sentence, commas included.
    assert chunks[1].endswith(".")
    assert "as well," in chunks[1]


async def test_clause_cuts_are_configurable():
    aggregator = ClauseAggregator(min_words=6, clause_cuts=0)
    text = "I can certainly help you with that order, and I will check the refund. "
    chunks = await feed_turn(aggregator, text)

    assert chunks == [text.strip()]


async def test_the_clause_budget_is_restored_for_the_next_turn():
    aggregator = ClauseAggregator(min_words=6)
    first = "I can certainly help you with that order, and I will check it now. "
    assert len(await feed_turn(aggregator, first)) == 2

    second = "I can certainly help you with that order, and I will check it now. "
    assert len(await feed_turn(aggregator, second)) == 2


async def test_the_ceiling_prefers_a_clause_boundary_to_a_bare_word_break():
    """A run-on that hits the ceiling should still end the chunk on a phrase."""
    aggregator = ClauseAggregator(min_words=4, max_words=8, clause_cuts=0)
    text = "alpha bravo charlie delta echo, foxtrot golf hotel india juliet kilo lima mike "
    chunks = await feed(aggregator, text, token_size=1)

    assert chunks[0] == "alpha bravo charlie delta echo,"


# ---------------------------------------------------------------------------
# TTS_CHUNKING=0
# ---------------------------------------------------------------------------


async def test_whole_turn_holds_everything_until_flush():
    """One request per turn: nothing is speakable before the reply is complete."""
    aggregator = WholeTurnAggregator()
    text = "Здравствуйте, это Анна. Хочу предложить вам бонус, займу минуту."

    assert await feed(aggregator, text) == []

    remaining = await aggregator.flush()
    assert remaining is not None
    assert remaining.text == text


async def test_whole_turn_emits_one_sentence_typed_chunk():
    aggregator = WholeTurnAggregator()
    await feed(aggregator, "Two sentences. Both in one request. ")

    remaining = await aggregator.flush()
    assert remaining.type == AggregationType.SENTENCE
    assert remaining.text == "Two sentences. Both in one request."


async def test_whole_turn_discards_the_buffer_on_interruption():
    aggregator = WholeTurnAggregator()
    await feed(aggregator, "the caller cut in halfway through")
    await aggregator.handle_interruption()

    assert await aggregator.flush() is None


async def test_whole_turn_starts_clean_on_the_next_turn():
    aggregator = WholeTurnAggregator()
    await feed(aggregator, "first reply.")
    await aggregator.flush()

    await feed(aggregator, "second reply.")
    remaining = await aggregator.flush()
    assert remaining.text == "second reply."
