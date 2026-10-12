"""The media leg's WebSocket output keeps a real-time playback clock.

Every serializer we use resamples through a stream resampler that buffers
across calls and emits nothing on most of them. Pipecat 1.8 treated those
calls as "not written": unpaced and not forwarded, so a reply left the
process at ~3.5x real time and the agent was declared silent while the far
end still had most of it queued.
"""

import asyncio
import time

from pipecat.frames.frames import (
    AudioRawFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    OutputAudioRawFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.observers.base_observer import BaseObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner
from starlette.websockets import WebSocketState

from src.integrations.telephony.websocket import PacedFastAPIWebsocketTransport

RATE = 16000
SECONDS = 1.0


class BufferingSerializer(FrameSerializer):
    """Emits audio on every fourth call, like a stream resampler."""

    def __init__(self):
        super().__init__()
        self._pending = b""
        self._calls = 0

    async def serialize(self, frame):
        if not isinstance(frame, AudioRawFrame):
            return None
        self._pending += frame.audio
        self._calls += 1
        if self._calls % 4:
            return None
        data, self._pending = self._pending, b""
        return data

    async def deserialize(self, data):
        return None


class Socket:
    client_state = application_state = WebSocketState.CONNECTED

    async def receive(self):
        await asyncio.sleep(3600)

    async def send_bytes(self, data):
        pass

    async def send_text(self, data):
        pass

    async def close(self, *args, **kwargs):
        pass


class Watch(BaseObserver):
    def __init__(self, output):
        super().__init__()
        self.output = output
        self.stopped_at = None
        self.forwarded = 0

    async def on_push_frame(self, data):
        frame = data.frame
        if isinstance(frame, BotStoppedSpeakingFrame) and self.stopped_at is None:
            self.stopped_at = time.monotonic()
        elif (
            data.source is self.output
            and data.direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, OutputAudioRawFrame)
        ):
            self.forwarded += 1


async def test_buffered_audio_is_paced_and_forwarded():
    socket = Socket()
    transport = PacedFastAPIWebsocketTransport(
        websocket=socket,
        params=FastAPIWebsocketParams(
            audio_out_enabled=True,
            audio_out_sample_rate=RATE,
            add_wav_header=False,
            serializer=BufferingSerializer(),
        ),
    )
    watch = Watch(transport.output())
    task = PipelineWorker(
        Pipeline([transport.output()]),
        params=PipelineParams(audio_out_sample_rate=RATE),
        observers=[watch],
    )
    audio = b"\x10\x00" * int(RATE * SECONDS)

    async def speak():
        await asyncio.sleep(0.2)
        started = time.monotonic()
        await task.queue_frames(
            [TTSStartedFrame(), TTSAudioRawFrame(audio, RATE, 1), TTSStoppedFrame()]
        )
        while watch.stopped_at is None:
            await asyncio.sleep(0.05)
        await task.queue_frame(EndFrame())
        return started

    async with asyncio.timeout(10):
        started, _ = await asyncio.gather(
            speak(), WorkerRunner(handle_sigint=False).run(task)
        )

    chunks = len(audio) // transport.output().audio_chunk_size
    assert watch.stopped_at - started >= 0.9 * SECONDS
    assert watch.forwarded == chunks


async def test_catch_up_output_makes_up_a_stall_but_not_an_idle_gap(monkeypatch):
    """The playground's clock keeps its schedule through a short stall.

    Pipecat restarts the clock from "now" after any late send, so a stall is
    lost for good and the browser's playback buffer stays that much shorter
    until it underruns. The catch-up output sends the stalled chunks at once
    instead — but after an idle gap it restarts rather than bursting.
    """
    from types import SimpleNamespace

    from src.integrations.telephony import websocket as ws

    clock = [100.0]
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(round(seconds, 6))
        clock[0] += seconds

    monkeypatch.setattr(ws, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(ws, "asyncio", SimpleNamespace(sleep=fake_sleep))
    transport = ws.CatchUpPacedFastAPIWebsocketTransport(
        websocket=Socket(),
        params=FastAPIWebsocketParams(
            audio_out_enabled=True,
            audio_out_sample_rate=RATE,
            add_wav_header=False,
            serializer=BufferingSerializer(),
        ),
    )
    output = transport.output()
    output._send_interval = 0.04

    for _ in range(3):
        await output._write_audio_sleep()
    assert sleeps == [0.0, 0.04, 0.04]

    sleeps.clear()
    clock[0] += 0.2  # a 200 ms event-loop stall: five 40 ms chunks behind
    for _ in range(6):
        await output._write_audio_sleep()
    assert sleeps == [0.0] * 5 + [0.04]

    sleeps.clear()
    clock[0] += 2.0  # silence, not a stall: restart instead of a 2 s burst
    for _ in range(2):
        await output._write_audio_sleep()
    assert sleeps == [0.0, 0.04]
