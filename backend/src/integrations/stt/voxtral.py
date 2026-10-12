"""Voxtral on vLLM's ``/v1/realtime``: the same route, a different dialect.

``mistralai/Voxtral-Mini-4B-Realtime`` is served by the same vLLM realtime
endpoint as Qwen3-ASR and accepts the identical handshake — the ``session.update``
in :meth:`Qwen3ASRService._start_message` is taken verbatim, ``model`` at the top
level included. What differs is everything about the *replies*, verified against
a live deployment:

===================  ==============================  =========================
                     Qwen3-ASR                       Voxtral
===================  ==============================  =========================
delta payload        ``language Russian<asr_text>…`` the transcript, nothing else
end of utterance     a trailing ``\\n``               no terminator at all
timing               deltas stream during speech     deltas arrive only after
                                                     ``input_audio_buffer.commit``
detected language    announced in the preamble       never reported
===================  ==============================  =========================

The first two rows are why the Qwen client returns nothing here rather than
failing loudly: :meth:`Qwen3ASRService._parse` looks for ``<asr_text>``, finds no
marker, and reports an empty transcript for every delta; and even with text, the
final frame is gated on a newline that never arrives.

So this subclass replaces the two methods that encode those assumptions. With no
terminator and no completion event, the end of an utterance has to be inferred:
the transcript is final once the deltas stop coming for
:data:`DEFAULT_FINALIZE_AFTER_MS`. That is a timer, not a protocol guarantee —
the one place this client is guessing, and it is deliberately the *only* one.

The upside of the missing preamble is that Voxtral does not language-guess:
frames carry the language the call was routed with instead of whatever the model
inferred from half a second of audio.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from loguru import logger
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.utils.time import time_now_iso8601

from src.application.engine.audio import AudioPath
from src.application.engine.capabilities import SttCapabilities
from src.application.engine.config import SttConfig
from src.common.enums.engine import SttAdapterEnum
from src.integrations.stt.base import SttAdapters
from src.integrations.stt.qwen3_asr import Qwen3ASRService

#: Quiet time after the last delta before the transcript is called final.
#: Voxtral emits its deltas in a burst after the commit, so this has to outlast
#: the gaps *within* that burst. Measured on the live endpoint: the longest gap
#: inside a call-length utterance (2.6s of speech) was 0.29s, rising to 1.06s on
#: a 28s stream that no single turn produces. 800ms clears the first with room
#: and costs that much before the final frame. The live pipeline waits for
#: that frame; the local ``flush()`` snapshot does not bypass finalization.
DEFAULT_FINALIZE_AFTER_MS: Final[int] = 800

#: Remaining uncertainties, in the same spirit as the Qwen client's.
PROTOCOL_ASSUMPTIONS: Final[tuple[str, ...]] = (
    "no completion event exists; silence after the last delta ends the utterance",
    "the server never sends session.updated, so config is assumed applied",
    "deltas are append-only within an utterance",
)


class VoxtralRealtimeService(Qwen3ASRService):
    """Voxtral-Mini-Realtime over vLLM's realtime WebSocket route."""

    protocol_assumptions: tuple[str, ...] = PROTOCOL_ASSUMPTIONS

    #: Every value measured against a live deployment.
    #:
    #: ``tail_silence_seconds``: Voxtral decodes until the audio stops, so a
    #: commit landing on the last word returns the utterance with its tail
    #: missing — 4.5s of speech committed with 0.5s of trailing silence came
    #: back four words short, 1.5s came back complete, 3s and 6s changed
    #: nothing.
    #:
    #: ``finalize_after_ms``: the longest gap between two deltas inside one
    #: call-length utterance was 0.29s, rising to 1.06s on a 28s stream that no
    #: single turn produces. 800ms clears the first with room to spare.
    capabilities: SttCapabilities = SttCapabilities(
        streams_during_speech=False,
        emits_completion_event=False,
        min_commit_seconds=5.0,
        tail_silence_seconds=1.5,
        finalize_after_ms=DEFAULT_FINALIZE_AFTER_MS,
        reports_language=False,
        accepts_language_hint=False,
    )

    @classmethod
    def from_config(
        cls, config: SttConfig, *, call_id: str, audio_path: AudioPath
    ) -> VoxtralRealtimeService:
        """Build a client from an organization's STT row."""
        return cls(
            ws_url=config.websocket_url(),
            api_key=config.model.provider.api_key,
            model=config.model.code,
            language=config.language or "en",
            session_id=call_id,
            audio_path=audio_path,
            finalize_after_ms=int(
                config.model.capabilities.get(
                    "finalize_after_ms", DEFAULT_FINALIZE_AFTER_MS
                )
            ),
        )

    def __init__(
        self, *, finalize_after_ms: int = DEFAULT_FINALIZE_AFTER_MS, **kwargs: Any
    ) -> None:
        """Initialise the client.

        Args:
            finalize_after_ms: Quiet time after the last delta before the
                utterance is treated as complete.
            **kwargs: Passed to :class:`Qwen3ASRService`.
        """
        super().__init__(**kwargs)
        self._finalize_after = max(0.05, finalize_after_ms / 1000)
        self._finalize_task: asyncio.Task | None = None

    async def _handle_delta(self, delta: str) -> None:
        """Fold one delta into the transcript and restart the quiet timer.

        Args:
            delta: The text fragment the server just sent. Empty deltas are
                common — Voxtral emits them between words — and are ignored
                rather than treated as an end marker.
        """
        if not delta:
            return

        self._raw += delta
        text = self._raw.strip()
        if not text:
            return

        update = self._tracker.update(text)
        self._utterance.partial = text
        frame = InterimTranscriptionFrame(
            text, self._user_id, time_now_iso8601(), self._language
        )
        frame.metadata["stable_prefix"] = update.stable_prefix
        frame.metadata["unstable_tail"] = update.unstable_tail
        await self.push_frame(frame)

        self._restart_finalize_timer()

    def _restart_finalize_timer(self) -> None:
        if self._finalize_task and not self._finalize_task.done():
            self._finalize_task.cancel()
        self._finalize_task = asyncio.create_task(self._finalize_when_quiet())

    async def _finalize_when_quiet(self) -> None:
        try:
            await asyncio.sleep(self._finalize_after)
        except asyncio.CancelledError:
            return
        await self._emit_final()

    async def _emit_final(self) -> None:
        """Push what has accumulated as the utterance's final transcript."""
        text = self._raw.strip()
        if not text:
            return

        self._utterance.finals.append(text)
        self._utterance.partial = ""
        self._tracker.reset()
        self._raw = ""
        logger.debug(
            f"{self}: final after {self._finalize_after * 1000:.0f}ms of quiet"
        )
        await self.push_frame(
            TranscriptionFrame(
                text,
                self._user_id,
                time_now_iso8601(),
                self._language,
                finalized=True,
            )
        )
        await self.emit_stt_usage_metrics()

    async def _disconnect_websocket(self) -> None:
        """Stop the pending timer before the socket goes away."""
        if self._finalize_task and not self._finalize_task.done():
            self._finalize_task.cancel()
        self._finalize_task = None
        await super()._disconnect_websocket()


SttAdapters[SttAdapterEnum.voxtral] = VoxtralRealtimeService
