"""Telephony adapters: registry, capability overrides, handshakes, the bridge wire.

No network anywhere: webhooks render to strings, media handshakes run against
a scripted fake WebSocket, and the bridge serializer is exercised as the pure
frame↔bytes converter it is.
"""

from __future__ import annotations

import json

import pytest
from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.frames.frames import (
    EndFrame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport

from src.common.enums.engine import TelephonyAdapterEnum
from src.integrations.telephony import (
    JambonzFrameSerializer,
    JambonzTelephonyAdapter,
    SipBridgeFrameSerializer,
    SipBridgeTelephonyAdapter,
    TelephonyConfig,
    TwilioTelephonyAdapter,
    build_telephony,
)
from src.integrations.telephony.jambonz import _answer_hook_url


class FakeWebsocket:
    """Just enough of a WebSocket for a media handshake."""

    def __init__(self, text_messages: list[str] | None = None) -> None:
        self.headers: dict[str, str] = {}
        self._texts = list(text_messages or [])

    async def receive_text(self) -> str:
        if not self._texts:
            raise AssertionError("handshake read past the scripted messages")
        return self._texts.pop(0)


def twilio_config(**overrides) -> TelephonyConfig:
    defaults = {
        "adapter": TelephonyAdapterEnum.twilio,
        "account_id": "AC-test",
        "auth_token": "token-test",
        "caller_id": "+15550000000",
    }
    defaults.update(overrides)
    return TelephonyConfig(**defaults)


def bridge_config(**overrides) -> TelephonyConfig:
    defaults = {"adapter": TelephonyAdapterEnum.sip_bridge}
    defaults.update(overrides)
    return TelephonyConfig(**defaults)


def jambonz_config(**overrides) -> TelephonyConfig:
    defaults = {
        "adapter": TelephonyAdapterEnum.jambonz,
        "account_id": "acct-test",
        "auth_token": "token-test",
        "caller_id": "+15550000000",
        "control_url": "https://jambonz.example.invalid",
    }
    defaults.update(overrides)
    return TelephonyConfig(**defaults)


# ---------------------------------------------------------------------------
# Registry and capability overrides
# ---------------------------------------------------------------------------


def test_the_registry_resolves_all_adapters():
    assert isinstance(
        build_telephony(twilio_config(), call_id="c1"), TwilioTelephonyAdapter
    )
    assert isinstance(
        build_telephony(bridge_config(), call_id="c1"), SipBridgeTelephonyAdapter
    )
    assert isinstance(
        build_telephony(jambonz_config(), call_id="c1"), JambonzTelephonyAdapter
    )


def test_capability_overrides_come_from_the_row():
    """A bridge that ships PCM16 at 16 kHz is a DB row, not a code change."""
    adapter = build_telephony(
        bridge_config(capabilities={"encoding": "pcm16", "sample_rate": 16000}),
        call_id="c1",
    )
    assert adapter.capabilities.encoding == "pcm16"
    assert adapter.capabilities.sample_rate == 16000
    # Untouched fields keep the adapter's defaults.
    assert adapter.capabilities.expects_start_event is True


def test_unknown_capability_overrides_are_ignored_not_fatal():
    adapter = build_telephony(bridge_config(capabilities={"tyop": True}), call_id="c1")
    assert adapter.capabilities.encoding == "ulaw"


# ---------------------------------------------------------------------------
# Twilio: webhook answer, media handshake, control preconditions
# ---------------------------------------------------------------------------


def test_twiml_routes_media_to_the_stream_url():
    adapter = build_telephony(twilio_config(), call_id="c1")
    twiml = adapter.answer_instructions("wss://calls.example.invalid/media?a=1&b=2")
    assert twiml.startswith('<?xml version="1.0"')
    assert "<Connect>" in twiml
    # Attribute-safe escaping: a raw ampersand is invalid XML.
    assert 'url="wss://calls.example.invalid/media?a=1&amp;b=2"' in twiml


async def test_twilio_handshake_reads_the_start_event():
    adapter = build_telephony(twilio_config(), call_id="c1")
    websocket = FakeWebsocket(
        [
            json.dumps({"event": "connected", "protocol": "Call"}),
            json.dumps(
                {"event": "start", "start": {"streamSid": "MZ-1", "callSid": "CA-1"}}
            ),
        ]
    )
    transport = await adapter.answer_media(websocket)
    assert isinstance(transport, FastAPIWebsocketTransport)
    serializer = transport._params.serializer
    assert serializer._stream_sid == "MZ-1"
    assert serializer._call_sid == "CA-1"


def test_twilio_auto_hangup_needs_credentials():
    with_creds = build_telephony(twilio_config(), call_id="c1")
    assert with_creds._auto_hang_up is True

    without = build_telephony(
        twilio_config(account_id=None, auth_token=None), call_id="c1"
    )
    assert without._auto_hang_up is False


async def test_twilio_dial_refuses_without_what_it_needs():
    no_creds = build_telephony(
        twilio_config(account_id=None, auth_token=None), call_id="c1"
    )
    with pytest.raises(ValueError, match="account_id"):
        await no_creds.dial(to="+15551111111", media_url="wss://x.invalid/m")

    no_caller = build_telephony(twilio_config(caller_id=None), call_id="c1")
    with pytest.raises(ValueError, match="caller_id"):
        await no_caller.dial(to="+15551111111", media_url="wss://x.invalid/m")


# ---------------------------------------------------------------------------
# SIP bridge: media handshake and control preconditions
# ---------------------------------------------------------------------------


async def test_bridge_handshake_reads_the_start_envelope():
    adapter = build_telephony(bridge_config(), call_id="c1")
    websocket = FakeWebsocket([json.dumps({"event": "start", "call_id": "leg-1"})])
    transport = await adapter.answer_media(websocket)
    assert isinstance(transport, FastAPIWebsocketTransport)
    assert isinstance(transport._params.serializer, SipBridgeFrameSerializer)


async def test_a_bridge_that_streams_immediately_skips_the_handshake():
    """expects_start_event=false is a row override; no read may happen."""
    adapter = build_telephony(
        bridge_config(capabilities={"expects_start_event": False}), call_id="c1"
    )
    # The fake raises if anything reads from it; an empty script proves no read.
    transport = await adapter.answer_media(FakeWebsocket([]))
    assert isinstance(transport, FastAPIWebsocketTransport)


async def test_bridge_control_needs_a_control_url():
    adapter = build_telephony(bridge_config(), call_id="c1")
    with pytest.raises(ValueError, match="control_url"):
        await adapter.dial(to="+15551111111", media_url="wss://x.invalid/m")
    with pytest.raises(ValueError, match="control_url"):
        await adapter.hangup("leg-1")


# ---------------------------------------------------------------------------
# The bridge wire: frames in, frames out
# ---------------------------------------------------------------------------


async def make_serializer(**kwargs) -> SipBridgeFrameSerializer:
    serializer = SipBridgeFrameSerializer(**kwargs)
    await serializer.setup(
        FrameProcessorSetup(
            clock=None,
            task_manager=None,
            pipeline_worker=None,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        )
    )
    return serializer


async def test_audio_round_trips_through_the_ulaw_wire():
    serializer = await make_serializer()
    pcm = b"\x00\x10" * 480  # 30ms of quiet-ish 16 kHz PCM16

    # The stream resampler buffers ~100ms before it starts emitting — normal
    # operation on a continuous call, same as the Twilio serializer — so feed
    # over a second of audio and judge what comes out the other side.
    wire = b""
    for _ in range(40):
        chunk = await serializer.serialize(
            OutputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1)
        )
        if chunk is not None:
            assert isinstance(chunk, bytes)  # binary on the wire, never JSON
            wire += chunk
    assert wire

    audio_frames = []
    for start in range(0, len(wire), 240):  # 30ms of 8 kHz µ-law per message
        frame = await serializer.deserialize(wire[start : start + 240])
        if frame is not None:
            audio_frames.append(frame)
    assert audio_frames
    for frame in audio_frames:
        assert isinstance(frame, InputAudioRawFrame)
        assert frame.sample_rate == 16000
        assert frame.audio


async def test_pcm16_encoding_is_a_config_choice():
    serializer = await make_serializer(encoding="pcm16", bridge_sample_rate=16000)
    pcm = b"\x00\x10" * 480

    wire = await serializer.serialize(
        OutputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1)
    )
    frame = await serializer.deserialize(wire)
    assert isinstance(frame, InputAudioRawFrame)
    assert frame.audio


async def test_barge_in_becomes_a_clear_envelope():
    serializer = await make_serializer()
    assert json.loads(await serializer.serialize(InterruptionFrame())) == {
        "event": "clear"
    }


async def test_the_stop_envelope_is_sent_once():
    serializer = await make_serializer()
    assert json.loads(await serializer.serialize(EndFrame())) == {"event": "stop"}
    assert await serializer.serialize(EndFrame()) is None


async def test_dtmf_envelopes_become_keypad_frames():
    serializer = await make_serializer()
    frame = await serializer.deserialize(json.dumps({"event": "dtmf", "digit": "5"}))
    assert isinstance(frame, InputDTMFFrame)
    assert frame.button == KeypadEntry.FIVE

    assert (
        await serializer.deserialize(json.dumps({"event": "dtmf", "digit": "Z"}))
        is None
    )


async def test_unknown_events_and_junk_are_survivable():
    serializer = await make_serializer()
    assert (
        await serializer.deserialize(json.dumps({"event": "stop", "reason": "bye"}))
        is None
    )
    assert await serializer.deserialize(json.dumps({"event": "mystery"})) is None
    assert await serializer.deserialize("not json at all") is None


def test_an_unsupported_encoding_is_refused_at_construction():
    with pytest.raises(ValueError, match="encoding"):
        SipBridgeFrameSerializer(encoding="opus")


# ---------------------------------------------------------------------------
# jambonz: media handshake, control preconditions, call_hook derivation
# ---------------------------------------------------------------------------


async def test_jambonz_opens_with_audio_no_handshake_read():
    """Confirmed live: the leg's first frame is binary audio, not a metadata
    frame — reading one throws. The fake raises if anything reads from it;
    an empty script proves answer_media never tries."""
    adapter = build_telephony(jambonz_config(), call_id="c1")
    assert adapter.capabilities.expects_start_event is False
    transport = await adapter.answer_media(FakeWebsocket([]))
    assert isinstance(transport, FastAPIWebsocketTransport)
    serializer = transport._params.serializer
    assert isinstance(serializer, JambonzFrameSerializer)
    # The rate is ours to know — it's what our own /answer webhook told
    # jambonz to use — not read off a wire that never announces it.
    assert serializer._bridge_rate == adapter.capabilities.sample_rate


async def test_jambonz_bridge_rate_follows_a_capability_override():
    adapter = build_telephony(
        jambonz_config(capabilities={"sample_rate": 16000}), call_id="c1"
    )
    transport = await adapter.answer_media(FakeWebsocket([]))
    assert transport._params.serializer._bridge_rate == 16000


async def test_jambonz_dial_refuses_without_what_it_needs():
    no_creds = build_telephony(
        jambonz_config(account_id=None, auth_token=None), call_id="c1"
    )
    with pytest.raises(ValueError, match="account_id"):
        await no_creds.dial(to="+15551111111", media_url="wss://x.invalid/media/c1")

    no_caller = build_telephony(jambonz_config(caller_id=None), call_id="c1")
    with pytest.raises(ValueError, match="caller_id"):
        await no_caller.dial(to="+15551111111", media_url="wss://x.invalid/media/c1")

    no_control_url = build_telephony(jambonz_config(control_url=None), call_id="c1")
    with pytest.raises(ValueError, match="control_url"):
        no_control_url._api_root()


def test_answer_hook_url_is_derived_from_the_media_url_not_minted_separately():
    """Same call uuid, same token, one derivation — jambonz's call_hook rides on it."""
    assert (
        _answer_hook_url("wss://calls.example.invalid/media/abc-123?t=tok")
        == "https://calls.example.invalid/media/abc-123/answer?t=tok"
    )
    # ws:// (unencrypted, e.g. local dev) maps to http:// the same way.
    assert _answer_hook_url("ws://localhost:8080/media/abc?t=x") == (
        "http://localhost:8080/media/abc/answer?t=x"
    )


# ---------------------------------------------------------------------------
# The jambonz wire: always raw PCM16, little-endian, mono
# ---------------------------------------------------------------------------


async def make_jambonz_serializer(**kwargs) -> JambonzFrameSerializer:
    kwargs.setdefault("bridge_sample_rate", 16000)
    serializer = JambonzFrameSerializer(**kwargs)
    await serializer.setup(
        FrameProcessorSetup(
            clock=None,
            task_manager=None,
            pipeline_worker=None,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        )
    )
    return serializer


async def test_audio_round_trips_as_raw_pcm16_no_codec_conversion():
    serializer = await make_jambonz_serializer()
    pcm = b"\x00\x10" * 480

    wire = await serializer.serialize(
        OutputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1)
    )
    assert isinstance(wire, bytes)  # binary on the wire, never JSON
    frame = await serializer.deserialize(wire)
    assert isinstance(frame, InputAudioRawFrame)
    assert frame.sample_rate == 16000
    assert frame.audio


async def test_barge_in_becomes_a_kill_audio_control_frame():
    serializer = await make_jambonz_serializer()
    assert json.loads(await serializer.serialize(InterruptionFrame())) == {
        "type": "killAudio"
    }


async def test_the_disconnect_frame_is_sent_once():
    serializer = await make_jambonz_serializer()
    assert json.loads(await serializer.serialize(EndFrame())) == {"type": "disconnect"}
    assert await serializer.serialize(EndFrame()) is None


async def test_disconnect_on_end_is_a_config_choice():
    serializer = await make_jambonz_serializer(send_disconnect_on_end=False)
    assert await serializer.serialize(EndFrame()) is None


async def test_dtmf_uses_the_dtmf_field_not_digit():
    """jambonz's DTMF envelope names the key ``dtmf``, unlike the generic bridge's ``digit``."""
    serializer = await make_jambonz_serializer()
    frame = await serializer.deserialize(json.dumps({"event": "dtmf", "dtmf": "5"}))
    assert isinstance(frame, InputDTMFFrame)
    assert frame.button == KeypadEntry.FIVE

    assert (
        await serializer.deserialize(json.dumps({"event": "dtmf", "dtmf": "Z"})) is None
    )
    # The generic bridge's key is ignored here — jambonz never sends it.
    assert (
        await serializer.deserialize(json.dumps({"event": "dtmf", "digit": "5"}))
        is None
    )


async def test_unknown_control_frames_and_junk_are_survivable():
    serializer = await make_jambonz_serializer()
    assert await serializer.deserialize(json.dumps({"type": "mystery"})) is None
    assert await serializer.deserialize("not json at all") is None
