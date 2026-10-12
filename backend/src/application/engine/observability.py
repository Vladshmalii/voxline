"""Structured logging with a per-call correlation ID, and turn latency tracing.

Two things live here:

* :func:`configure_logging` / :func:`new_call_id` — every log line carries a
  ``call_id`` so a single call can be grepped out of a busy process.
* :class:`TurnLatencyObserver` — a Pipecat observer that timestamps each stage of
  a turn and prints one summary line per turn. This is how acceptance criterion 2
  is verified: the summary states, in milliseconds, whether the first TTS audio
  was produced *before* the LLM finished generating. If that ever flips to
  ``overlap=NO``, the LLM→TTS streaming path has been broken — most likely by
  someone "simplifying" the chunking in services/chunking.py.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

_LOG_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
    "<cyan>{extra[call_id]}</cyan> | <level>{message}</level>"
)


def configure_logging(level: str = "INFO") -> None:
    """Install a single stderr sink carrying the call correlation ID.

    Args:
        level: Minimum level to emit (``DEBUG``/``INFO``/...).
    """
    logger.remove()
    logger.configure(extra={"call_id": "-"})
    logger.add(sys.stderr, level=level, format=_LOG_FORMAT, enqueue=False)


def new_call_id() -> str:
    """Generate a short correlation ID for one call."""
    return uuid.uuid4().hex[:8]


def call_logger(call_id: str):
    """Return a logger bound to a call ID."""
    return logger.bind(call_id=call_id)


def _ms(ns: int) -> float:
    return ns / 1_000_000.0


def _delta_ms(start: float | None, end: float | None) -> int | None:
    """A stage duration in whole milliseconds, or None when a mark is missing."""
    if start is None or end is None:
        return None
    return round(end - start)


@dataclass
class _TurnTimings:
    """Stage timestamps for one turn, in pipeline-clock milliseconds."""

    user_started: float | None = None
    #: How long the agent sat listening before the caller spoke — measured
    #: from the previous BotStoppedSpeaking (or call start), which outlives
    #: the per-turn reset, so it is computed at user_started and stored.
    waiting_ms: int | None = None
    speech_end: float | None = None
    turn_commit: float | None = None
    llm_start: float | None = None
    llm_first_token: float | None = None
    llm_end: float | None = None
    tts_first_request: float | None = None
    tts_first_audio: float | None = None
    #: When the output transport actually started pushing this turn's audio
    #: onto the wire (``BotStartedSpeakingFrame``, raised by the transport
    #: itself, right before it hands the frame to the telephony socket) — not
    #: to be confused with ``tts_first_audio``, which only means synthesis
    #: produced bytes, not that the caller's leg ever received them.
    bot_started_speaking: float | None = None
    #: When the caller started speaking while this turn's reply was still in
    #: flight or playing.
    interrupted_at: float | None = None
    seen: set[int] = field(default_factory=set)

    def delta(self, start: float | None, end: float | None) -> str:
        if start is None or end is None:
            return "—"
        return f"{end - start:.0f}ms"


class TurnLatencyObserver(BaseObserver):
    """Timestamps each stage of a turn and logs one summary line when it ends.

    Placed on the ``PipelineTask``; it sees every frame transfer without sitting
    in the pipeline, so it adds no latency of its own.
    """

    def __init__(self, *, call_id: str = "-") -> None:
        """Initialise the observer.

        Args:
            call_id: Correlation ID stamped on every line this observer emits.
        """
        super().__init__()
        self._log = call_logger(call_id)
        self._turn = _TurnTimings()
        self._turn_index = 0
        #: When the agent last yielded the floor (previous BotStoppedSpeaking,
        #: or call start). Consumed by the next UserStartedSpeaking to compute
        #: how long the caller was waited for; None while the agent holds the
        #: floor, so a barge-in reports no waiting time rather than a stale one.
        self._listening_since: float | None = None
        #: Called with one structured payload per turn, after the summary log
        #: line. Wired by the session to its hooks; None costs nothing.
        self.notify: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    async def on_push_frame(self, data: FramePushed) -> None:
        """Record stage timestamps as frames flow between processors."""
        frame = data.frame
        at = _ms(data.timestamp)

        # A frame crosses many processor boundaries; only the first sighting is
        # the stage timestamp we want.
        if frame.id in self._turn.seen:
            return

        if isinstance(frame, StartFrame):
            self._turn.seen.add(frame.id)
            self._listening_since = at
        elif isinstance(frame, UserStartedSpeakingFrame):
            if self._turn.llm_start is not None:
                # The agent still held the floor — its reply was being
                # generated or played — so the caller cut that turn short.
                # Report it now: left open, it would be overwritten below and
                # the cut-short reply never reported at all.
                self._turn.interrupted_at = at
                await self._summarise()
            self._turn = _TurnTimings()
            self._turn.seen.add(frame.id)
            self._turn.user_started = at
            self._turn.waiting_ms = _delta_ms(self._listening_since, at)
            self._listening_since = None
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._mark(frame, "speech_end", at)
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._mark(frame, "turn_commit", at)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._mark(frame, "llm_start", at)
        elif isinstance(frame, LLMTextFrame):
            self._mark(frame, "llm_first_token", at, once=True)
        elif isinstance(frame, TTSStartedFrame):
            self._mark(frame, "tts_first_request", at, once=True)
        elif isinstance(frame, TTSAudioRawFrame):
            self._mark(frame, "tts_first_audio", at, once=True)
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._mark(frame, "bot_started_speaking", at, once=True)
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._mark(frame, "llm_end", at)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._turn.seen.add(frame.id)
            await self._summarise()
            self._listening_since = at

    def _mark(self, frame: Frame, stage: str, at: float, *, once: bool = False) -> None:
        self._turn.seen.add(frame.id)
        if once and getattr(self._turn, stage) is not None:
            return
        setattr(self._turn, stage, at)
        self._log.debug(f"turn stage {stage} @ {at:.0f}ms")

    async def _summarise(self) -> None:
        t = self._turn
        if t.turn_commit is None and t.llm_start is None:
            return  # Nothing interesting happened (e.g. a canned prompt).
        self._turn_index += 1

        # The headline number: did TTS start producing audio before the LLM was
        # done generating? If not, the pipeline is serialising two stages that
        # must overlap, and voice-to-voice latency is roughly double what it
        # should be.
        overlap = "—"
        if t.tts_first_audio is not None and t.llm_end is not None:
            lead = t.llm_end - t.tts_first_audio
            overlap = f"YES (+{lead:.0f}ms)" if lead > 0 else f"NO ({lead:.0f}ms)"

        voice_to_voice = t.delta(t.speech_end, t.tts_first_audio)

        self._log.info(
            f"turn {self._turn_index} latency | "
            f"speech_end→commit {t.delta(t.speech_end, t.turn_commit)} | "
            f"commit→llm_first_token {t.delta(t.turn_commit, t.llm_first_token)} | "
            f"llm_first_token→tts_request {t.delta(t.llm_first_token, t.tts_first_request)} | "
            f"tts_request→first_audio {t.delta(t.tts_first_request, t.tts_first_audio)} | "
            f"first_audio→transport_out {t.delta(t.tts_first_audio, t.bot_started_speaking)} | "
            f"voice-to-voice {voice_to_voice} | llm/tts overlap {overlap}"
        )
        if t.tts_first_audio is not None and t.bot_started_speaking is None:
            # Synthesis produced bytes but the output transport never reported
            # BotStartedSpeakingFrame — the caller's leg likely never heard
            # this turn even though tts_request→first_audio looks healthy.
            self._log.warning(
                f"turn {self._turn_index}: TTS produced audio but the transport "
                "never confirmed it started playing (no BotStartedSpeakingFrame) "
                "— audio may not have reached the caller"
            )
        if self.notify is not None:
            # The same marks the log line prints, as data. Semantics:
            # stt_ms is caller-stopped→transcript-committed, which is the turn
            # cascade's decision time plus transcript finalisation — the STT
            # itself streams during speech and has no isolated cost to report.
            await self.notify(
                {
                    "event": "timing",
                    "turn": self._turn_index,
                    "waiting_user_ms": t.waiting_ms,
                    "user_turn_ms": _delta_ms(t.user_started, t.turn_commit),
                    "stt_ms": _delta_ms(t.speech_end, t.turn_commit),
                    "ttt_first_token_ms": _delta_ms(t.llm_start, t.llm_first_token),
                    "ttt_ms": _delta_ms(t.llm_start, t.llm_end),
                    "tts_ms": _delta_ms(t.tts_first_request, t.tts_first_audio),
                    "voice_to_voice_ms": _delta_ms(t.speech_end, t.tts_first_audio),
                    "interrupted": t.interrupted_at is not None,
                }
            )
        self._turn = _TurnTimings()
