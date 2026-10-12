"""The WebSocket transport every media leg runs on, with Pipecat 1.8's pacing fixed.

Pipecat 1.8.0 (pipecat#91b58ec4) made ``_write_frame`` report whether a
payload reached the socket, and the output transport now treats "nothing
sent" as "not taken": it skips the playback-clock sleep and does not push the
frame downstream. Every serializer we use resamples through a stream
resampler that buffers across calls and emits nothing on most of them, so
most chunks went out unpaced — a 14 s reply left in ~4 s, and the transport
raised ``BotStoppedSpeakingFrame`` while the far end still had ~10 s queued.
The silence prompt then fired over the reply's tail, the end-call gate could
hang up before the farewell finished playing, and the spoken-text tracker
downstream saw a third of the audio.

Fixed upstream in 1.10.0 (pipecat#a186aecc): a frame the serializer took is
taken, payload or not. This mirrors that fix; drop it once Pipecat is ≥ 1.10.

The playground's browser leg additionally catches up after a stall
(:class:`CatchUpPacedFastAPIWebsocketTransport`): Pipecat's clock restarts
from "now" whenever a send is late, so every event-loop stall is lost for
good and shrinks the far end's buffer until it underruns — audible gaps on a
CPU-limited admin pod. Telephony legs keep the stock clock.
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketOutputTransport,
    FastAPIWebsocketTransport,
)


class _PacedOutputTransport(FastAPIWebsocketOutputTransport):
    """Paces and forwards audio the serializer buffered without emitting."""

    async def _write_frame(self, frame: Frame) -> bool:
        """Serialize and send a frame; True once the serializer has taken it."""
        if self._client.is_closing or not self._client.is_connected:
            return False
        if not self._params.serializer:
            return False
        try:
            payload = await self._params.serializer.serialize(frame)
            if not payload:
                return True
            packet_bytes = self._params.fixed_audio_packet_size
            if packet_bytes and isinstance(payload, (bytes, bytearray)):
                self._audio_send_buffer.extend(bytes(payload))
                while len(self._audio_send_buffer) >= packet_bytes:
                    chunk = bytes(self._audio_send_buffer[:packet_bytes])
                    del self._audio_send_buffer[:packet_bytes]
                    await self._client.send(chunk)
                return True
            await self._client.send(payload)
        except Exception as e:  # noqa: BLE001 - same contract as upstream
            logger.error(f"{self} exception sending data: {e.__class__.__name__} ({e})")
            return False
        return True


#: How far behind its playback clock the catch-up output may fall and still
#: make the time up by sending at once. Further behind than this is an idle
#: gap or an interruption (Pipecat zeroes the clock on one), not a stall, and
#: the clock restarts instead of bursting.
CATCH_UP_SECONDS = 0.5


class _CatchUpPacedOutputTransport(_PacedOutputTransport):
    """Paced output that keeps its schedule through short stalls."""

    async def _write_audio_sleep(self) -> None:
        now = time.monotonic()
        if now - self._next_send_time > CATCH_UP_SECONDS:
            self._next_send_time = now
        await asyncio.sleep(max(0.0, self._next_send_time - now))
        self._next_send_time += self._send_interval


class PacedFastAPIWebsocketTransport(FastAPIWebsocketTransport):
    """``FastAPIWebsocketTransport`` whose output keeps real-time pacing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._output = _PacedOutputTransport(
            self, self._client, self._params, name=self._output_name
        )


class CatchUpPacedFastAPIWebsocketTransport(FastAPIWebsocketTransport):
    """Paced output whose clock makes up a short stall instead of losing it.

    For a far end that buffers playback itself (the playground's browser): a
    stall's chunks go out at once afterwards, so its buffer refills rather
    than staying short for the rest of the reply.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._output = _CatchUpPacedOutputTransport(
            self, self._client, self._params, name=self._output_name
        )
