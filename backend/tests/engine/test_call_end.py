"""Model-requested hangup through real tool dispatch, TTS and paced playback."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    EndWorkerFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMTextFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import NOT_GIVEN
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallFromLLM, FunctionCallParams
from pipecat.services.openai.tts import OpenAITTSSettings
from pipecat.tests.utils import SleepFrame, run_test

from src.application.engine.call_end import CallEndGate, end_call_tool
from src.application.engine.config import CallContext, CustomerProfile
from src.application.engine.context.interruption import (
    SpokenAssistantAggregator,
    SpokenTextTracker,
)
from src.application.engine.pipeline import build_context
from src.application.engine.silence import ConnectAndFeedbackSilenceHandler
from src.integrations.tts.qwen3_tts import Qwen3TTSService
from src.integrations.ttt.openai_compatible import OpenAICompatibleLLMService
from tests.engine.conftest import make_agent, make_profile
from tests.engine.test_interruption import PacedOutput


class LocalLLM(OpenAICompatibleLLMService):
    def __init__(self, goodbye, *, duplicate=False):
        super().__init__(api_key="test")
        self.goodbye = goodbye
        self.duplicate = duplicate
        self.requests = 0

    async def _process_context(self, context):
        self.requests += 1
        if self.requests == 1:
            await self.run_function_calls(
                [
                    FunctionCallFromLLM(
                        context=context,
                        tool_call_id=f"end-{i}",
                        function_name="end_call",
                        arguments={"goodbye": self.goodbye},
                    )
                    for i in range(2 if self.duplicate else 1)
                ]
            )
        else:
            await self.push_frame(LLMTextFrame("Of course, go ahead."))


class LocalTTS(Qwen3TTSService):
    def __init__(self, *, seconds=0.18, synth_delay=0, no_audio=False):
        super().__init__(
            api_key="test", settings=OpenAITTSSettings(model="test", voice="test")
        )
        self.seconds = seconds
        self.synth_delay = synth_delay
        self.no_audio = no_audio
        self.requests = []

    async def run_tts(self, text, context_id):
        self.requests.append(text)
        await asyncio.sleep(self.synth_delay)
        if not self.no_audio:
            yield TTSAudioRawFrame(
                b"\x10\x00" * round(self.sample_rate * self.seconds),
                self.sample_rate,
                1,
                context_id=context_id,
            )


class RecordedOutput(PacedOutput):
    def __init__(self):
        super().__init__(sample_rate=24000)
        self.bytes_played = 0
        self.bytes_at_end = None

    async def write_audio_frame(self, frame):
        result = await super().write_audio_frame(frame)
        self.bytes_played += len(frame.audio)
        return result

    async def stop(self, frame):
        self.bytes_at_end = self.bytes_played
        await super().stop(frame)


def components(goodbye="До свидания!", *, duplicate=False, **tts_options):
    profile = make_profile()
    silence = ConnectAndFeedbackSilenceHandler(profile=profile)
    context, _, _ = build_context(
        profile,
        CallContext(call_id="call-end-test", org_uuid="org"),
        end_call=end_call_tool(silence.handle_end_call),
    )
    llm = LocalLLM(goodbye, duplicate=duplicate)
    tts = LocalTTS(**tts_options)
    output = RecordedOutput()
    tracker = SpokenTextTracker()
    assistant = SpokenAssistantAggregator(
        context, tracker=tracker, estimate_partial_text=True
    )
    pipeline = Pipeline(
        [
            silence,
            llm,
            tts,
            tracker,
            output,
            assistant,
            CallEndGate(silence.complete_end_call),
        ]
    )
    return pipeline, context, silence, llm, tts, output


async def exercise(parts, frames, *, natural_end=False):
    pipeline, _, _, llm, tts, _ = parts
    try:
        async with asyncio.timeout(4):
            _, up = await run_test(
                pipeline, frames_to_send=frames, send_end_frame=not natural_end
            )
        return [f for f in up if isinstance(f, EndWorkerFrame)]
    finally:
        await llm._client.close()
        await tts._client.close()


@pytest.mark.parametrize(
    "goodbye, expected", [("До свидания!", "До свидания!"), (" ", "Goodbye.")]
)
async def test_tool_speaks_once_and_ends_only_after_audio_without_another_llm_run(
    goodbye, expected
):
    parts = components(goodbye)
    _, context, silence, llm, tts, output = parts
    endings = await exercise(parts, [LLMContextFrame(context)], natural_end=True)
    assert len(endings) == 1
    assert llm.requests == 1
    assert tts.requests == [expected]
    assert output.bytes_at_end == round(output.sample_rate * 0.18) * 2
    assert any(m.get("content") == expected for m in context.messages)
    assert any(m.get("role") == "tool" for m in context.messages)
    assert silence._timer is None


async def test_previous_audio_finishing_cannot_hang_up_before_the_farewell():
    parts = components(synth_delay=0.1)
    _, context, _, llm, tts, output = parts
    endings = await exercise(
        parts,
        [TTSSpeakFrame("Previous answer."), SleepFrame(0.03), LLMContextFrame(context)],
        natural_end=True,
    )
    assert len(endings) == 1
    assert llm.requests == 1
    assert tts.requests == ["Previous answer.", "До свидания!"]
    assert output.bytes_at_end == round(output.sample_rate * 0.18) * 2 * 2


async def test_duplicate_tool_calls_do_not_repeat_the_goodbye_or_hangup():
    parts = components(duplicate=True)
    endings = await exercise(parts, [LLMContextFrame(parts[1])], natural_end=True)
    assert len(endings) == 1
    assert parts[4].requests == ["До свидания!"]


@pytest.mark.parametrize("synth_delay", [0, 0.25])
async def test_interruption_during_synthesis_or_playback_cancels_hangup_and_allows_reply(
    synth_delay,
):
    parts = components(seconds=0.4, synth_delay=synth_delay)
    _, context, _, llm, tts, _ = parts
    endings = await exercise(
        parts,
        [
            LLMContextFrame(context),
            SleepFrame(0.12),
            UserStartedSpeakingFrame(),
            InterruptionFrame(),
            UserStoppedSpeakingFrame(),
            SleepFrame(0.05),
            LLMContextFrame(context),
            SleepFrame(0.8),
        ],
    )
    assert endings == []
    assert llm.requests == 2
    assert tts.requests[-1] == "Of course, go ahead."


async def test_tts_without_audio_still_ends_the_call():
    parts = components(no_audio=True)
    endings = await exercise(parts, [LLMContextFrame(parts[1])], natural_end=True)
    assert len(endings) == 1
    assert parts[5].bytes_at_end == 0


@pytest.mark.parametrize(
    "cancellation", [UserStartedSpeakingFrame, InterruptionFrame, CancelFrame, EndFrame]
)
async def test_delayed_tool_callback_and_old_marker_cannot_revive_cancelled_hangup(
    cancellation,
):
    handler = ConnectAndFeedbackSilenceHandler(profile=make_profile())
    # These tasks normally belong to the live pipeline's task manager.
    handler.create_task = asyncio.create_task

    async def cancel(task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    handler.cancel_task = cancel
    handler.push_frame = AsyncMock()
    result = AsyncMock()
    params = FunctionCallParams(
        function_name="end_call",
        tool_call_id="one",
        arguments={"goodbye": "Bye."},
        llm=None,
        pipeline_worker=None,
        context=None,
        result_callback=result,
    )
    await handler.handle_end_call(params)
    old_id = handler._end_call_request
    callback = result.call_args.kwargs["properties"].on_context_updated
    await handler.process_frame(cancellation(), FrameDirection.DOWNSTREAM)
    await callback()
    await handler.complete_end_call(old_id)
    assert not any(
        isinstance(c.args[0], (TTSSpeakFrame, EndWorkerFrame))
        for c in handler.push_frame.call_args_list
    )
    assert handler._timer is None


@pytest.mark.parametrize("value", [None, 123, "x" * 301])
async def test_malformed_tool_arguments_do_not_close_the_call(value):
    handler = ConnectAndFeedbackSilenceHandler(profile=make_profile())
    result = AsyncMock()
    await handler.handle_end_call(
        FunctionCallParams(
            function_name="end_call",
            tool_call_id="bad",
            arguments={"goodbye": value},
            llm=None,
            pipeline_worker=None,
            context=None,
            result_callback=result,
        )
    )
    assert not handler._closing
    assert "error" in result.call_args.args[0]
    assert result.call_args.kwargs["properties"].run_llm is True


@pytest.mark.parametrize(
    "supports_tools, sms, expected",
    [
        (None, False, ["end_call"]),
        (False, False, []),
        (True, True, ["end_call", "send_sms"]),
    ],
)
async def test_live_pipeline_advertises_end_call_by_default_and_preserves_sms(
    monkeypatch, supports_tools, sms, expected
):
    from src.application.engine import pipeline as module

    profile = make_profile()
    if supports_tools is not None:
        profile.ttt.model.capabilities["supports_tools"] = supports_tools
    agent = make_agent(
        sms_tool_enabled=sms,
        sms_tool_message="Your bonus is waiting." if sms else "",
    )
    call = CallContext(
        call_id="tools-test",
        org_uuid="org",
        customer=CustomerProfile(customer_id="caller", phone="+15550001111"),
    )
    tts = LocalTTS()
    monkeypatch.setattr(module, "build_stt", lambda *args, **kwargs: FrameProcessor())
    monkeypatch.setattr(module, "build_tts", lambda *args: tts)
    monkeypatch.setattr(module, "build_vad", lambda *args: None)
    monkeypatch.setattr(module, "build_turn_analyzer", lambda *args: None)
    transport = SimpleNamespace(input=FrameProcessor, output=RecordedOutput)
    send_sms = AsyncMock(return_value="SMS sent.")
    built = module.build_pipeline(
        profile=profile,
        call=call,
        transport=transport,
        agent=agent,
        send_sms=send_sms,
    )
    try:
        tools = (
            []
            if built.context.tools is NOT_GIVEN
            else built.context.tools.standard_tools
        )
        assert [tool.name for tool in tools] == expected
        if sms:
            # VOAD-60: the model only marks intent; the operator's fixed text
            # goes out once the call has ended, never mid-conversation.
            result = AsyncMock()
            await tools[1].handler(
                FunctionCallParams(
                    function_name="send_sms",
                    tool_call_id="sms",
                    arguments={},
                    llm=built.ttt,
                    pipeline_worker=built.task,
                    context=built.context,
                    result_callback=result,
                )
            )
            result.assert_awaited_once_with(
                "Noted. The message will be sent automatically once the call ends."
            )
            assert built.sms_intent.requested
            send_sms.assert_not_awaited()
    finally:
        await built.task.cleanup()
        await built.ttt._client.close()
        await tts._client.close()


async def test_live_pipeline_hangs_up_when_a_provider_can_no_longer_work(
    monkeypatch,
):
    # Pipecat's default keeps running past a rejected key or a 404 endpoint,
    # leaving the caller in silence until the idle timeout.
    from src.application.engine import pipeline as module

    tts = LocalTTS()
    monkeypatch.setattr(module, "build_stt", lambda *args, **kwargs: FrameProcessor())
    monkeypatch.setattr(module, "build_tts", lambda *args: tts)
    monkeypatch.setattr(module, "build_vad", lambda *args: None)
    monkeypatch.setattr(module, "build_turn_analyzer", lambda *args: None)
    transport = SimpleNamespace(input=FrameProcessor, output=RecordedOutput)
    built = module.build_pipeline(
        profile=make_profile(),
        call=CallContext(call_id="dead-provider", org_uuid="org"),
        transport=transport,
    )
    try:
        assert built.task._processor_unusable_policy is ProcessorUnusablePolicy.END
    finally:
        await built.task.cleanup()
        await built.ttt._client.close()
        await tts._client.close()
