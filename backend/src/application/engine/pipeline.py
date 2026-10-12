"""Assembling one call's pipeline from a resolved profile.

Everything here is decided by :class:`ResolvedProfile` — which recogniser, which
voice, how long a pause may run before the turn commits, whether the reply is
chunked. Nothing reads the environment, and no vendor module is imported: the
adapters arrive through the registries in ``src/integrations``.

These placements in the pipeline are load-bearing and easy to undo by accident:

* ``silence`` sits upstream of the LLM, so the lines it speaks reach TTS, and
  downstream of the transport's upstream bot-speaking frames, so it knows when
  the agent is talking.
* ``spoken_tracker`` collects synthesis metadata before the output transport;
  ``assistant_aggregator`` uses paced output frames after it to save heard text
  on interruption, before Pipecat writes the assistant message into context.
* ``CallEndGate`` sits after output and assistant aggregation: the model's
  farewell must finish playing and enter history before shutdown is requested.
* ``max_duration`` sits right after ``silence`` (upstream of the LLM, same as
  it) so it can inject its own goodbye into TTS and see the same upstream
  bot-speaking frames the silence handler relies on to know when it may act.
* ``switcher`` (when the agent's policy enables it) sits directly between the
  recogniser and the user aggregator: downstream of the recogniser because its
  STT settings update is pushed upstream and must reach it first, upstream of
  the aggregator because a confirmed switch must be in force before the
  confirming utterance commits to the LLM.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import (
    PipelineParams,
    PipelineWorker,
    ProcessorUnusablePolicy,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from src.application.engine.audio import ASR_SAMPLE_RATE, AudioPath
from src.application.engine.call_end import CallEndGate, end_call_tool
from src.application.engine.config import CallContext, ResolvedProfile, VoiceAgentConfig
from src.application.engine.context.assembly import (
    AgentScript,
    CustomerProfile,
    PromptAssembler,
)
from src.application.engine.context.interruption import (
    SpokenAssistantAggregator,
    SpokenTextTracker,
)
from src.application.engine.context.user import CallUserAggregator
from src.application.engine.language_switch import LanguageSwitcher
from src.application.engine.observability import TurnLatencyObserver
from src.application.engine.silence import ConnectAndFeedbackSilenceHandler
from src.application.engine.sms_intent import SmsIntent
from src.application.engine.turn.controller import CascadingTurnStopStrategy
from src.application.engine.turn.max_duration import MaxDurationHandler
from src.common.enums.engine import SmsMessageStatusEnum
from src.integrations.stt.base import BaseSttAdapter, build_stt
from src.integrations.tts.base import BaseTtsAdapter, build_tts
from src.integrations.ttt.base import BaseTttAdapter, build_ttt
from src.integrations.vad.base import build_turn_analyzer, build_vad

#: Sends one SMS to the caller and reports back what happened, in words the
#: model can relay ("SMS sent", "SMS failed: ..."). Closes over the org and
#: the DB session the engine itself is not allowed to hold — see
#: ``src/application/worker/runner.py``, the only place this is built.
SmsSender = Callable[[str], Awaitable[str]]


def _sms_tool_schema(message: str, intent: SmsIntent) -> FunctionSchema:
    """The "send_sms" function advertised to the model, when the agent enables it.

    The model neither writes the message (VOAD-60: the operator fixed it
    ahead of time) nor sends it directly — calling this only marks intent;
    ``CallSession.run`` sends the actual SMS once the call has ended, never
    mid-conversation. The fixed text still rides in the description below so
    the model can judge whether sending *this* message now is appropriate,
    even though it can't change it.

    Args:
        message: The operator-authored, already-approved SMS body.
        intent: Marked when the model decides to send it.

    Returns:
        A schema carrying its own handler, so no separate
        ``llm.register_function`` call is needed.
    """

    async def handler(params: FunctionCallParams) -> None:
        intent.mark_requested()
        await params.result_callback(
            "Noted. The message will be sent automatically once the call ends."
        )

    return FunctionSchema(
        name="send_sms",
        description=(
            "Send the caller a pre-written SMS to their own phone number. "
            f'The message is fixed and reads exactly: "{message}". Call this '
            "with no arguments when the conversation makes it appropriate to "
            "send that message — it goes out automatically once the call "
            "ends, not immediately."
        ),
        properties={},
        required=[],
        handler=handler,
    )


@dataclass(slots=True)
class PipelineTaps:
    """Extra processors an edge splices into the pipeline at fixed points.

    For observers a transport wants that the engine has no business knowing
    about — the playground's caption taps are the motivating case. A tap must
    forward every frame untouched: the load-bearing orderings in the module
    docstring assume nothing between the named processors withholds traffic.
    """

    #: Directly after the recogniser — the last stop where user transcription
    #: frames still exist (the user aggregator consumes rather than forwards
    #: them). Upstream traffic to the recogniser passes through unharmed.
    after_stt: tuple[FrameProcessor, ...] = ()
    #: Between TTS and the output transport — where the agent's spoken text
    #: passes on its way to the wire.
    before_output: tuple[FrameProcessor, ...] = ()


@dataclass(slots=True)
class BuiltPipeline:
    """A pipeline and the handles a session needs to drive it."""

    task: PipelineWorker
    context: LLMContext
    stt: BaseSttAdapter
    tts: BaseTtsAdapter
    ttt: BaseTttAdapter
    vad: VADAnalyzer
    audio_path: AudioPath
    #: The per-turn latency tracker. The session wires its ``notify`` to the
    #: hooks so timings reach whoever is listening (the playground UI, a
    #: worker persisting metrics) without the observer knowing who.
    latency: TurnLatencyObserver
    #: Present only when the agent's policy enables mid-call switching.
    language_switcher: LanguageSwitcher | None = None
    #: Present only when the SMS tool was actually offered this call (VOAD-60)
    #: — None means there is nothing to check for a deferred send at all.
    sms_intent: SmsIntent | None = None


def build_context(
    profile: ResolvedProfile,
    call: CallContext,
    *,
    agent: VoiceAgentConfig | None = None,
    send_sms: SmsSender | None = None,
    end_call: FunctionSchema | None = None,
) -> tuple[LLMContext, PromptAssembler, SmsIntent | None]:
    """Build the LLM context in prefix-cache order.

    Layer 1 is the agent's instructions and script — identical for every call in
    this language, so the server caches it once. Layer 2 is this customer.
    Layer 3, the conversation, is appended as it happens. Anything per-call that
    creeps into layer 1 costs the cache on every call in the fleet.

    Args:
        profile: The call's resolved settings.
        call: This call's context, including the customer.
        agent: The full agent, for tool toggles that live outside the
            resolved profile (``sms_tool_enabled``). None disables SMS.
        send_sms: Whether SMS infrastructure exists for this call at all
            (None disables the tool regardless of the agent's toggle) — the
            sender itself is only actually called later, at call end.
        end_call: The live pipeline's farewell/shutdown tool, if supported.

    Returns:
        The context, the assembler that produced it (for signatures), and
        the SMS intent marker the tool writes to — None when the tool was
        not offered this call (toggle off, no phone number, message blank,
        or still pending moderation).

    Note:
        The tool list is fixed here, once, and never changes for the rest of
        the call — advertising tools mid-call would shift the serialized
        prefix the chat template puts ahead of the messages, invalidating the
        cache exactly like an unstable system prompt.
    """
    customer = None
    if call.customer and call.customer.customer_id:
        customer = CustomerProfile(
            customer_id=call.customer.customer_id,
            name=call.customer.name,
            language=profile.language,
            attributes=call.customer.attributes,
            offers=tuple(call.customer.offers),
        )
    assembler = PromptAssembler(
        AgentScript(
            system_prompt=profile.prompts.system_prompt,
            script=profile.prompts.call_script,
        ),
        customer,
    )

    tools = [end_call] if end_call is not None else []
    sms_ready = (
        agent is not None
        and agent.sms_tool_enabled
        and send_sms is not None
        and bool(agent.sms_tool_message)
        and agent.sms_tool_message_status == SmsMessageStatusEnum.approved
    )
    sms_intent: SmsIntent | None = None
    if sms_ready and call.customer and call.customer.phone:
        sms_intent = SmsIntent()
        tools.append(_sms_tool_schema(agent.sms_tool_message, sms_intent))

    context_kwargs = {"messages": assembler.initial_messages()}
    if tools:
        context_kwargs["tools"] = ToolsSchema(standard_tools=tools)
    return LLMContext(**context_kwargs), assembler, sms_intent


def build_pipeline(
    *,
    profile: ResolvedProfile,
    call: CallContext,
    transport: BaseTransport,
    audio_path: AudioPath | None = None,
    agent: VoiceAgentConfig | None = None,
    taps: PipelineTaps | None = None,
    send_sms: SmsSender | None = None,
) -> BuiltPipeline:
    """Build everything one call needs, from its resolved profile.

    Args:
        profile: The call's settings after the agent/language/call merge.
        call: Correlation ids and per-call facts.
        transport: The media leg. WebRTC in development, SIP in production —
            nothing downstream of ``transport.input()`` knows which.
        audio_path: Per-call converters. One is created if not supplied.
        agent: The full agent, enabling mid-call language switching when its
            policy asks for it. None — a diagnostics run or a test that has
            only a profile — leaves switching off, since without the language
            rows there is nothing to switch to.
        taps: Extra processors the transport's edge wants spliced in. None
            for a phone leg.
        send_sms: Sender the session calls once, at call end, if the model
            invoked the tool. None leaves the tool off entirely regardless of
            ``agent.sms_tool_enabled`` — a diagnostics run or a test with no
            infrastructure behind it — since there would be nothing able to
            deliver it later.

    Returns:
        The pipeline task and the service handles the session drives.
    """
    taps = taps or PipelineTaps()
    audio_path = audio_path or AudioPath(asr_sample_rate=ASR_SAMPLE_RATE)

    stt = build_stt(profile.stt, call_id=call.call_id, audio_path=audio_path)
    tts = build_tts(profile.tts, profile.chunking)
    ttt = build_ttt(profile.ttt)

    vad = build_vad(profile.vad, ASR_SAMPLE_RATE)
    turn_analyzer = build_turn_analyzer(profile.turn, ASR_SAMPLE_RATE)
    stop_strategy = CascadingTurnStopStrategy(
        turn_analyzer=turn_analyzer, profile=profile
    )

    silence = ConnectAndFeedbackSilenceHandler(
        profile=profile,
        prompt_seconds=profile.silence.prompt_seconds,
        max_prompts=profile.silence.max_prompts,
        reset_timeout_seconds=profile.silence.reset_timeout_seconds,
        max_no_answer_prompts=profile.silence.max_no_answer_prompts,
        feedback_delay_seconds=profile.silence.feedback_delay_seconds,
        client_name=call.customer.name if call.customer else "",
    )
    context, assembler, sms_intent = build_context(
        profile,
        call,
        agent=agent,
        send_sms=send_sms,
        end_call=end_call_tool(silence.handle_end_call)
        if ttt.capabilities.supports_tools
        else None,
    )
    user_aggregator = CallUserAggregator(
        context,
        params=LLMUserAggregatorParams(
            vad_analyzer=vad,
            user_turn_strategies=UserTurnStrategies(stop=[stop_strategy]),
        ),
    )
    spoken_tracker = SpokenTextTracker()
    assistant_aggregator = SpokenAssistantAggregator(
        context,
        tracker=spoken_tracker,
        estimate_partial_text=not tts.capabilities.streams_incrementally,
        _paired_user_aggregator=user_aggregator,
    )
    max_duration = MaxDurationHandler(
        max_duration_seconds=profile.max_duration_seconds,
        goodbye=profile.spoken.goodbye,
    )

    switcher: LanguageSwitcher | None = None
    if agent is not None and agent.language_switch.enabled:
        switcher = LanguageSwitcher(
            agent=agent,
            call=call,
            profile=profile,
            stt=stt,
            strategy=stop_strategy,
            silence=silence,
            context=context,
            assembler=assembler,
        )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            *taps.after_stt,
            *(() if switcher is None else (switcher,)),
            user_aggregator,
            silence,
            max_duration,
            ttt,
            tts,
            *taps.before_output,
            spoken_tracker,
            transport.output(),
            assistant_aggregator,
            CallEndGate(silence.complete_end_call),
        ]
    )

    latency = TurnLatencyObserver(call_id=call.call_id)
    task = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[latency],
        conversation_id=call.call_id,
        idle_timeout_secs=profile.idle_timeout_seconds,
        # A recogniser or voice that can no longer work — a rejected key, a
        # 404 endpoint, reconnects exhausted — would otherwise leave the
        # caller in silence until the idle timeout. Nothing in a phone leg
        # can fail over mid-call, so end it: queued audio still drains first.
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )

    return BuiltPipeline(
        task=task,
        context=context,
        stt=stt,
        tts=tts,
        ttt=ttt,
        vad=vad,
        audio_path=audio_path,
        latency=latency,
        language_switcher=switcher,
        sms_intent=sms_intent,
    )
