"""Clause-boundary chunking of the LLM token stream for TTS.

**This module is the reason the agent sounds fast. Read before changing.**

The LLM streams tokens. Waiting for the full response before calling TTS puts
voice-to-voice latency at 1.5–2 s, because nothing at all is synthesised until
the last token lands. Instead, each chunk is dispatched to TTS *while the LLM is
still generating*, so synthesis of sentence one overlaps generation of sentence
two, and the caller hears audio roughly as soon as the first clause exists.

The obvious "simplification" — collect the response, then speak it — deletes that
overlap and roughly doubles the latency. :class:`~observability.TurnLatencyObserver`
exists partly to catch that regression: it prints ``llm/tts overlap NO`` when the
first audio arrives after generation finished.

Chunking rule, from the spec: emit on sentence-ending punctuation, or after
~8–10 tokens, whichever comes first. Implemented as three tiers:

1. **Sentence boundary** — always emits. Best prosody, handled by the base class.
2. **Clause boundary past ``min_words``** — a comma, semicolon, colon or dash
   once enough words have accumulated. "After N tokens" is taken to mean *at the
   next clause boundary* after N tokens rather than *exactly at* token N, because
   cutting mid-phrase produces audibly wrong intonation and the TTS has no way to
   recover it.
3. **Hard ceiling at ``max_words``** — a run-on with no punctuation at all would
   otherwise never flush and would stall the whole overlap. Cut at the last
   clause delimiter in the buffer if there is one, and only at a bare word
   boundary if there is not.

Only the **first** chunk of a turn is cut at a clause, because only the first
chunk is on the latency path. Measured against the deployed Qwen3-TTS:

* The server does not synthesise incrementally — time to first byte tracks the
  length of the input (0.7 s for 4 words, 1.4 s for 13, 3.8 s for 37). So one
  request per turn would put first audio nearly four seconds out. Chunking is
  not optional.
* Every request is an independent sample. The *same* sentence resynthesised
  comes back 2.4 s, 2.5 s, then 3.6 s long, with RMS between 2451 and 5025 —
  a different speaking rate and up to 6 dB of level between takes. ``seed``,
  ``temperature`` and ``top_p`` are accepted by the endpoint and demonstrably
  ignored: three requests with a fixed seed return three different waveforms.

Those two facts pull in opposite directions, and the split above is where they
balance. Each request is a fresh draw of the speaker, so *every extra chunk in a
turn is another chance for the voice to change mid-sentence*. Cutting at clauses
after the first chunk buys latency nobody is waiting on and pays for it in
identity drift, so subsequent chunks run to a sentence end — full context for
the model to place stress and intonation, and as few draws per turn as the
latency budget allows. Synthesis stays comfortably ahead of playback either way:
the measured real-time factor is 0.21–0.29, so a six-second sentence is ready in
about 1.4 s while the previous chunk is still speaking.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Final

from pipecat.utils.text.base_text_aggregator import Aggregation, AggregationType
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

#: Mid-sentence break points. Ordered by how natural a pause sounds after them.
CLAUSE_DELIMITERS: Final[frozenset[str]] = frozenset(
    {",", ";", ":", "—", "–", "、", "，", "；", "："}
)

DEFAULT_MIN_WORDS: Final[int] = 8
#: Chunks per turn that may end at a clause rather than a sentence. Only the
#: first chunk is on the latency path; see the module docstring for the
#: measurements behind this.
DEFAULT_CLAUSE_CUTS: Final[int] = 1
#: Ceiling as a multiple of min_words. 2.5× ≈ 20 words at the default, about six
#: seconds of speech — long enough that the seam is rare, short enough that a
#: run-on sentence cannot stall the pipeline.
MAX_WORDS_FACTOR: Final[float] = 2.5


def _word_count(text: str) -> int:
    return len(text.split())


class ClauseAggregator(SimpleTextAggregator):
    """Splits streaming LLM text into speakable chunks at clause granularity.

    Drop-in replacement for Pipecat's :class:`SimpleTextAggregator`, which only
    breaks at sentence ends. On a long first sentence that difference is the
    difference between speaking in 300 ms and speaking in 1.5 s.
    """

    def __init__(
        self,
        *,
        min_words: int = DEFAULT_MIN_WORDS,
        max_words: int | None = None,
        clause_cuts: int = DEFAULT_CLAUSE_CUTS,
        **kwargs,
    ) -> None:
        """Initialise the aggregator.

        Args:
            min_words: Words that must accumulate before a clause boundary is
                allowed to end a chunk.
            max_words: Hard ceiling; defaults to ``min_words * MAX_WORDS_FACTOR``.
            clause_cuts: How many chunks per turn may be cut at a clause instead
                of a sentence end. The default of 1 covers the only chunk on the
                latency path; 0 is sentence-only; a larger number trades voice
                consistency for time to first audio.
            **kwargs: Passed to :class:`SimpleTextAggregator`.
        """
        super().__init__(**kwargs)
        self._min_words = max(1, min_words)
        self._max_words = (
            max_words if max_words is not None else int(min_words * MAX_WORDS_FACTOR)
        )
        self._max_words = max(self._max_words, self._min_words + 1)
        self._clause_cuts = max(0, clause_cuts)
        self._chunks_emitted = 0

    @property
    def min_words(self) -> int:
        """Words required before a clause boundary may end a chunk."""
        return self._min_words

    @property
    def max_words(self) -> int:
        """Words after which a chunk is cut regardless of punctuation."""
        return self._max_words

    @property
    def clause_cuts(self) -> int:
        """Chunks per turn that may be cut at a clause boundary."""
        return self._clause_cuts

    async def aggregate(self, text: str) -> AsyncIterator[Aggregation]:
        """Accumulate streamed text and yield chunks as they become speakable.

        Args:
            text: The next slice of LLM output. Usually one token.

        Yields:
            Chunks ready to hand to TTS, in order.
        """
        if self._aggregation_type == AggregationType.TOKEN:
            async for aggregation in super().aggregate(text):
                yield aggregation
            return

        for char in text:
            self._text += char

            sentence = await self._check_sentence_with_lookahead(char)
            if sentence:
                self._chunks_emitted += 1
                yield sentence
                continue

            # A sentence boundary awaiting lookahead must not be pre-empted by a
            # clause cut, or "$29. Next" gets split at the wrong place.
            if self._needs_lookahead:
                continue

            clause = self._maybe_cut_clause(char)
            if clause:
                self._chunks_emitted += 1
                yield clause

    def _maybe_cut_clause(self, char: str) -> Aggregation | None:
        """Cut at a clause boundary, or at the ceiling, if this character allows it."""
        words = _word_count(self._text)

        if (
            char in CLAUSE_DELIMITERS
            and words >= self._min_words
            and self._chunks_emitted < self._clause_cuts
        ):
            return self._emit(len(self._text))

        # Ceiling: only ever cut on whitespace, so a word is never split in two.
        if char.isspace() and words >= self._max_words:
            return self._emit(self._ceiling_cut_point())

        return None

    def _ceiling_cut_point(self) -> int:
        """Where to cut a run-on that hit ``max_words``.

        The last clause delimiter in the buffer is a far better seam than the
        arbitrary word boundary the ceiling landed on — the TTS at least ends
        the chunk on a phrase. Only accepted if it leaves a chunk worth speaking;
        otherwise the ceiling's own cut point stands.
        """
        for index in range(len(self._text) - 1, -1, -1):
            if self._text[index] in CLAUSE_DELIMITERS:
                head = self._text[: index + 1]
                if _word_count(head) >= self._min_words:
                    return index + 1
                break
        return len(self._text)

    async def handle_interruption(self) -> None:
        """Drop the buffer and start the next turn on a fresh clause budget."""
        await super().handle_interruption()
        self._chunks_emitted = 0

    async def reset(self) -> None:
        """Clear the buffer. Called by ``flush()``, i.e. once per turn."""
        await super().reset()
        self._chunks_emitted = 0

    def _emit(self, upto: int) -> Aggregation | None:
        chunk = self._text[:upto].strip(" ")
        self._text = self._text[upto:]
        if not chunk:
            return None
        return Aggregation(text=chunk, type=AggregationType.SENTENCE)


class WholeTurnAggregator(SimpleTextAggregator):
    """Holds the entire reply and speaks it in one request (``TTS_CHUNKING=0``).

    The opposite trade from :class:`ClauseAggregator`, and the reason it exists:
    one request per turn is one draw of the speaker, so the voice, the speaking
    rate and the level cannot change halfway through a reply, and the model sees
    the whole text before it decides how to say any of it.

    It costs the entire overlap. Nothing is synthesised until the LLM has
    finished generating, and this server does not stream synthesis either — time
    to first byte tracks the length of the input — so first audio lands roughly
    at *generation time + synthesis time* instead of after the first clause.
    Expect ``llm/tts overlap NO`` from
    :class:`~observability.TurnLatencyObserver`; here that is the setting doing
    what it was asked to, not a regression.

    Use it to judge how the voice *should* sound, then decide how much of that
    quality the latency budget can buy back.
    """

    async def aggregate(self, text: str) -> AsyncIterator[Aggregation]:
        """Accumulate the reply. Nothing is speakable until ``flush()``.

        Args:
            text: The next slice of LLM output.

        Yields:
            Nothing, in SENTENCE mode. TOKEN mode is passed through to the base
            class, which has no buffering to disable.
        """
        if self._aggregation_type == AggregationType.TOKEN:
            async for aggregation in super().aggregate(text):
                yield aggregation
            return

        self._text += text
        return
        # Never reached. The bare `yield` below is what makes this an async
        # generator rather than a coroutine returning None — without it,
        # `async for` over aggregate() raises TypeError.
        yield  # pragma: no cover
