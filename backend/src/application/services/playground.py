"""The playground: talk to an agent over a browser WebSocket, no telephony.

The whole point is fidelity — this runs the *real* path (rows →
``build_agent_config`` → ``resolve_profile`` → ``CallSession`` with the full
pipeline: VAD, turn cascade, interruption bookkeeping, language switching),
so what an operator hears here is what a caller will hear. Only the edges
differ from a phone call: the transport is the operator's browser instead of
a carrier, and nothing is persisted — no Call row, no registry entry, no
liveness lock. A playground conversation is a rehearsal, not a record.

Wire contract (the browser side):

* send: binary frames of raw PCM16 mono @ 16 kHz (mic audio, ~20 ms chunks);
* receive: binary frames of raw PCM16 mono @ 16 kHz (the agent's voice),
  plus JSON text frames —
  ``{"event": "transcript", "role": "user"|"assistant", "text": …,
  "final": …}`` for live captions;
  ``{"event": "state", "state": "listening"|"user_speaking"|"thinking"|
  "speaking"}`` narrating what the agent is doing (emitted on change, and
  once at session start);
  ``{"event": "interruption", "while": "thinking"|"speaking"}`` when the
  operator starts speaking before the agent finished;
  ``{"event": "tool_call", "name": …, "arguments": …, "result": …}`` once a
  tool call (``send_sms``, ``end_call``, …) has actually run (VOAD-58) —
  the UI renders this as a friendly line instead of raw JSON;
  ``{"event": "timing", "turn": n, "waiting_user_ms": …, "user_turn_ms": …,
  "stt_ms": …, "ttt_first_token_ms": …, "ttt_ms": …, "tts_ms": …,
  "voice_to_voice_ms": …, "interrupted": …}`` once per turn — the latency
  observer's stage durations (null where a stage did not happen, e.g. no
  user part on the greeting turn);
  ``{"event": "clear"}`` on barge-in (drop buffered playback immediately);
  and ``{"event": "stop"}`` when the session ends;
* closing the socket ends the session; the agent's idle timeout also applies.

The serializer extends the sip-bridge one (same binary-audio-plus-JSON
envelope shape) rather than inventing a third dialect; the addition is
captions, which a phone leg has no use for but a playground UI lives on.

This module imports the engine (and pipecat) at module level and is imported
*lazily* by the controller — the admin app boots without the pipeline stack
and pays for it on the first playground session.
"""

from __future__ import annotations

import json
import uuid

from fastapi import WebSocket
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

from src.application.engine.config import CallContext
from src.application.engine.pipeline import PipelineTaps
from src.application.engine.session import CallSession, SessionHooks
from src.application.engine.ui_events import (
    AgentStateTap,
    CaptionTap,
    ToolCallTap,
    UiEventEmitter,
)
from src.common.enums.engine import CallDirectionEnum
from src.core.db.session import SessionMaker
from src.integrations.telephony.sip_bridge import SipBridgeFrameSerializer
from src.integrations.telephony.websocket import (
    CatchUpPacedFastAPIWebsocketTransport,
)
from src.models.agent import VoiceAgent
from src.repositories.agent import VoiceAgentCRUD, build_agent_config

#: One rate both ways: matches the recogniser's input rate, so mic audio is
#: never resampled twice, and keeps the browser-side audio worklet trivial.
PLAYGROUND_SAMPLE_RATE = 16000


class PlaygroundSerializer(SipBridgeFrameSerializer):
    """The bridge wire plus live captions.

    Captions and agent-state events arrive as transport-message frames minted
    by the :mod:`~src.application.engine.ui_events` taps; the payload is
    already the wire envelope, so serialization is a dump. They must ride
    transport messages because the output transport hands its serializer
    nothing else that is not audio or control — a bare transcription frame
    never reaches this method (see the ui_events module). Everything else is
    the parent's contract.
    """

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(
            frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)
        ):
            return json.dumps(frame.message)
        return await super().serialize(frame)


async def run_playground(
    websocket: WebSocket, *, org_uuid: str, agent_id: int, language: str | None = None
) -> None:
    """Run one playground conversation over an accepted-to-be socket.

    Args:
        websocket: The operator's WebSocket, not yet accepted.
        org_uuid: The operator's organization (from auth).
        agent_id: The agent to talk to.
        language: Optional call language; defaults to the agent's.

    Close codes: 4404 unknown agent, 4500 configuration failed to build.
    """
    async with SessionMaker.get_session(org_uuid)() as session:
        agent_row = await VoiceAgentCRUD(session).get_one_or_none(
            VoiceAgent.id == agent_id
        )
        if agent_row is None:
            await websocket.close(code=4404)
            return
        try:
            agent_config = build_agent_config(agent_row)
        except ValueError as exc:
            logger.warning(f"playground: agent {agent_id} config invalid: {exc}")
            await websocket.close(code=4500)
            return

    await websocket.accept()

    # Catch-up pacing: the browser buffers playback itself, and an admin pod's
    # event-loop stalls must refill that buffer, not drain it for good.
    transport = CatchUpPacedFastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=PLAYGROUND_SAMPLE_RATE,
            add_wav_header=False,
            serializer=PlaygroundSerializer(
                encoding="pcm16",
                bridge_sample_rate=PLAYGROUND_SAMPLE_RATE,
            ),
        ),
    )

    context = CallContext(
        call_id=f"playground-{uuid.uuid4().hex[:10]}",
        org_uuid=org_uuid,
        # Outbound on purpose: the agent greets first, which is the very first
        # thing an operator wants to hear.
        direction=CallDirectionEnum.outbound,
        language=language,
    )

    emitter = UiEventEmitter()

    async def forward_timing(_call_id: str, payload: dict) -> None:
        await emitter.emit(payload)

    call_session = CallSession(
        agent=agent_config,
        call=context,
        transport=transport,
        # Per-turn latency breakdowns arrive through the session's hooks (the
        # observer cannot push frames itself) and enter the wire via the
        # emitter tap.
        hooks=SessionHooks(on_turn_timing=forward_timing),
        # The after-stt tap catches the caller's transcripts before the user
        # aggregator consumes them; before the output transport, one tap
        # catches the agent's spoken text on its way to the wire and the other
        # narrates the agent's state (listening/thinking/speaking,
        # interruptions) from the frames that all pass that point.
        taps=PipelineTaps(
            after_stt=(CaptionTap(),),
            before_output=(CaptionTap(), AgentStateTap(), ToolCallTap(), emitter),
        ),
    )
    logger.info(
        f"playground: {context.call_id} started for agent {agent_id} in org {org_uuid}"
    )
    try:
        await call_session.run()
    except Exception:  # noqa: BLE001 - a playground crash must not 500 the app
        logger.exception(f"playground: {context.call_id} failed")
    finally:
        logger.info(f"playground: {context.call_id} finished")
