"""The engine's configuration schemas: one call's setup, fully typed.

Relocated from ``src/application/engine/config.py`` so every pydantic schema
lives under ``src/schemas`` (platform convention); the engine re-exports them
and owns the merge logic (``resolve_profile``) that gives them meaning. The
docstring below is the contract, unchanged:

Nothing here reads the environment and nothing here touches the ORM. These are
plain pydantic schemas — the same role `S*Cache` schemas play for the chat
adapters — so the engine can be driven from an organization's rows, from a
fixture in a test, or from a diagnostics command, with no code path knowing the
difference.

Three layers, merged by :func:`src.application.engine.config.resolve_profile`:

1. :class:`VoiceAgentConfig` — the agent's defaults, per organization.
2. :class:`LanguageConfig` — what differs for one language: voice, prompts,
   turn timings, the words that mark an unfinished sentence.
3. :class:`CallContext` — what only this call knows: who is being called, in
   which language, and any per-call override of the two layers above.

The merge is one-level-deep and explicit: a language may replace whole sections,
never half of one. That keeps "why did this call use that voice" answerable by
reading two rows instead of reasoning about inheritance.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.common.enums.engine import (
    CallDirectionEnum,
    ChunkingModeEnum,
    SmsMessageStatusEnum,
    SttAdapterEnum,
    TtsAdapterEnum,
    TttAdapterEnum,
    TurnAnalyzerEnum,
    VadAdapterEnum,
)
from src.utils.url import websocket_url

# ---------------------------------------------------------------------------
# Providers and models
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """Where a model is served and how to authenticate to it.

    One organization's Voxtral and another's are different endpoints with
    different keys, so this is per-call data rather than deployment config, and
    a client built from it must never be shared between calls.
    """

    url: str
    api_key: str | None = None
    #: Anything the adapter accepts that is not worth a column: proxy settings,
    #: a non-standard path, a vendor flag under test.
    options: dict[str, Any] = Field(default_factory=dict)


class ModelConfig(BaseModel):
    """A served model, plus the parts of its behaviour the engine must know.

    ``capabilities`` overrides what the adapter class declares. It exists
    because the same client code faces servers that disagree about the protocol
    they implement — one Qwen3-ASR deployment finalises on a newline, a Voxtral
    deployment goes quiet instead — and those differences belong in data, where
    an operator can correct them, rather than in a branch nobody can reach.
    """

    code: str
    provider: ProviderConfig
    capabilities: dict[str, Any] = Field(default_factory=dict)


#: Default WebSocket route per recogniser; the self-hosted backends ride vLLM's
#: realtime endpoint, Cartesia serves its own. Kept here, next to the config
#: that resolves it, rather than on the adapter classes, because the readiness
#: probe must derive exactly the URI a call would dial without importing the
#: pipeline stack (pipecat).
#: An adapter served somewhere other than "/" registers its route in this map.
STT_WS_ROUTES: dict[SttAdapterEnum, str] = {
    SttAdapterEnum.qwen3_asr: "/v1/realtime",
    SttAdapterEnum.voxtral: "/v1/realtime",
    SttAdapterEnum.cartesia: "/stt/websocket",
    SttAdapterEnum.deepgram: "/v1/listen",
}


class SttConfig(BaseModel):
    """Speech-to-text for a call."""

    adapter: SttAdapterEnum
    model: ModelConfig
    #: Sent to backends that accept a language hint, and used to tag frames on
    #: the ones that do not. Falls back to the call's language.
    language: str | None = None

    def websocket_url(self) -> str:
        """The WebSocket URI a client for this config dials.

        The provider row stores one HTTP base URL for all three model kinds —
        the scheme and route are wire-protocol facts of the adapter, not of
        where the model is served. A row can still pin the URI outright (a
        ``ws(s)://`` URL is used verbatim) or override just the route with
        ``provider.options["ws_path"]``. Both the adapters' ``from_config``
        and the readiness probe resolve through here, so the probe can never
        disagree with the URL a live call would use.
        """
        route = self.model.provider.options.get(
            "ws_path", STT_WS_ROUTES.get(self.adapter, "")
        )
        return websocket_url(self.model.provider.url, route)


class TtsConfig(BaseModel):
    """Text-to-speech for a call."""

    adapter: TtsAdapterEnum
    model: ModelConfig
    voice: str
    #: Language the synthesiser is told to speak. Falls back to the call's
    #: language in ``resolve_profile``, exactly as ``SttConfig.language`` does —
    #: without it a synthesiser that takes an explicit language (Qwen3-TTS,
    #: Cartesia) runs the first turn on its own default and only learns the
    #: call's language if a mid-call switch happens to send it one.
    language: str | None = None
    #: Rate the service emits. The transport resamples; nothing else should.
    sample_rate: int = 24000
    speed: float | None = None
    instructions: str | None = None


class TttConfig(BaseModel):
    """The LLM, and the sampling it runs with."""

    adapter: TttAdapterEnum
    model: ModelConfig
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    #: Reasoning models think by default and a phone call cannot wait for it.
    #: Left None the adapter sends nothing and the server's default stands.
    enable_thinking: bool | None = False
    #: Escape hatch, merged into the request's ``extra_body``.
    extra_body: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Listening: VAD, turn taking, silence
# ---------------------------------------------------------------------------


class VadConfig(BaseModel):
    """Voice activity detection. Runs in-process on every frame."""

    adapter: VadAdapterEnum = VadAdapterEnum.silero
    confidence: float = 0.7
    start_secs: float = 0.2
    #: Speech-to-silence before the VAD reports a stop. The turn controller
    #: decides what that stop *means*; see :class:`TurnParams`.
    stop_secs: float = 0.2
    min_volume: float = 0.6


class TurnParams(BaseModel):
    """When a pause becomes the caller's turn ending.

    The cascade: below ``min_delay_ms`` the caller is almost certainly
    mid-breath and an inference is wasted; between min and max the analyzer is
    asked every ``repoll_ms``; at ``max_delay_ms`` the turn commits regardless.
    The ceiling is load-bearing, not a safety net — it is what stops a caller
    who trails off from being ignored.
    """

    analyzer: TurnAnalyzerEnum = TurnAnalyzerEnum.smart_turn_v3
    #: Whether to consult the analyzer at all for this language. False drops to
    #: ``silence_fallback_ms``, which is the honest setting for a language the
    #: analyzer was never trained on.
    smart_turn: bool = True
    min_delay_ms: int = 200
    max_delay_ms: int = 3000
    repoll_ms: int = 400
    #: Used only when ``smart_turn`` is false: commit this long after speech ends.
    silence_fallback_ms: int = 1100
    #: Maximum STT wait from the actual end of speech. A missing final must
    #: produce a re-prompt, never an answer to an unfinished interim transcript.
    transcript_timeout_ms: int = Field(default=3000, ge=0)

    @model_validator(mode="after")
    def _check_window(self) -> TurnParams:
        """Reject a window that cannot hold a cascade.

        A floor above the ceiling means the analyzer is never consulted and
        every turn commits late; a non-positive repoll is a busy loop. Both are
        configuration mistakes worth refusing at the edge, where the message
        names the organization's row, rather than at 2am on a live call.
        """
        if self.min_delay_ms > self.max_delay_ms:
            raise ValueError(
                f"min_delay_ms ({self.min_delay_ms}) exceeds max_delay_ms ({self.max_delay_ms})"
            )
        if self.repoll_ms <= 0:
            raise ValueError("repoll_ms must be positive")
        return self

    # Seconds, for the code that schedules with them. Milliseconds are what an
    # operator types; seconds are what asyncio takes.
    @property
    def min_delay(self) -> float:
        """Floor before the analyzer is consulted, in seconds."""
        return self.min_delay_ms / 1000.0

    @property
    def max_delay(self) -> float:
        """Hard ceiling from end of speech, in seconds."""
        return self.max_delay_ms / 1000.0

    @property
    def repoll_interval(self) -> float:
        """How often to re-ask the analyzer while waiting, in seconds."""
        return self.repoll_ms / 1000.0

    @property
    def silence_fallback(self) -> float:
        """Commit delay when the analyzer is off, in seconds."""
        return self.silence_fallback_ms / 1000.0


class FragmentParams(BaseModel):
    """What a ceiling commit is allowed to send to the LLM.

    An utterance cut at ``max_delay_ms`` may be half a sentence. Answering half
    a sentence is worse than asking the caller to go on, so a commit that looks
    unfinished is re-prompted instead.
    """

    min_words: int = 2
    #: Ending on one of these means the caller was still assembling the sentence.
    dangling_tokens: frozenset[str] = frozenset()
    #: Short utterances that are nonetheless whole turns: "yes", "no", "да".
    complete_short: frozenset[str] = frozenset()


class SpokenPrompts(BaseModel):
    """Lines the agent speaks without asking the LLM.

    Localised per language, and deliberately not model output: they must be
    instant, identical every time, and safe to say when the model is unreachable.
    """

    silence: str
    reprompt: str
    goodbye: str
    #: Repeated while the caller has picked up but never spoken, in place of
    #: the silent ``reset_timeout_seconds`` hangup — see
    #: ``SilencePolicy.max_no_answer_prompts``. Empty (the default) keeps the
    #: original behaviour: no line spoken, just a silent hangup once the
    #: timeout elapses.
    no_answer: str = ""
    #: Jinja template for VOAD-27's feedback request (``feedback_delay_seconds``
    #: of silence after the agent's last reply). Unlike the three lines above,
    #: this one is a template, not literal text — it needs the caller's name
    #: substituted in via ``utils.script.render_script`` — and rendering is
    #: deliberately not done here: this schema only carries the source string
    #: through the merge, the same way ``prompts.call_script`` does. Empty
    #: means the organization has not configured one.
    feedback_request: str = ""


class SilencePolicy(BaseModel):
    """How long to tolerate a caller saying nothing, and what to do about it."""

    prompt_seconds: float = 9.0
    max_prompts: int = 2
    #: Full silence for this long right after connect (or since our own last
    #: turn) repeats ``SpokenPrompts.no_answer`` — distinct from
    #: prompt_seconds/max_prompts, which apply once the caller has spoken at
    #: least once and it goes quiet mid-conversation.
    reset_timeout_seconds: float = 20.0
    #: Unanswered ``no_answer`` prompts before giving up and hanging up (no
    #: goodbye — nobody has ever answered to say it to). An org that has not
    #: set ``SpokenPrompts.no_answer`` never reaches this: the original
    #: single silent wait, then hangup, still applies.
    max_no_answer_prompts: int = 2
    #: Silence for this long after the agent's last reply speaks
    #: ``VoiceAgent.spoken_feedback_request`` (rendered with the caller's
    #: name), asking for feedback instead of repeating the reprompt.
    feedback_delay_seconds: float = 15.0


# ---------------------------------------------------------------------------
# Speaking
# ---------------------------------------------------------------------------


class ChunkingConfig(BaseModel):
    """How the reply is cut on its way to TTS.

    Each chunk is a separate synthesis request, and a request is an independent
    draw of the speaker, so chunk count trades latency against how much the
    voice can drift inside one answer. ``clause_cuts`` is the compromise: only
    the chunks on the latency path may be cut at a clause, the rest run to a
    sentence end.
    """

    mode: ChunkingModeEnum = ChunkingModeEnum.clause
    min_words: int = 8
    max_words: int | None = None
    clause_cuts: int = 1
    #: Scale every chunk after the first to the loudness of the first, so level
    #: cannot jump between requests. Costs nothing on the path to first audio.
    match_loudness: bool = True


class PromptSet(BaseModel):
    """The three LLM-facing strings that make up a call, in one language.

    Written natively per language rather than translated at runtime: a model
    follows an instruction in the language it is answering in far more reliably,
    and a fixed string is prefix-cacheable where a generated one is not.
    """

    system_prompt: str
    call_script: str = ""
    #: Stands in for the caller's first turn on an outbound call. Phrase it as a
    #: stage direction — anything that reads like dialogue risks the model
    #: answering it instead of opening the conversation.
    greeting_kickoff: str = ""


class LanguageSwitchPolicy(BaseModel):
    """Whether a caller's detected language may retarget a live call.

    Off by default: a switch rewrites the prompt layers, which burns the prefix
    cache once, so it is an explicit organization choice rather than a surprise.
    Only languages the agent has configured (or its default) are candidates —
    switching to a language with no row would change the voice and nothing
    else, which is the half-switched call this policy exists to prevent.

    The detection signal comes from the recogniser
    (``BaseSttAdapter.detected_language``). Backends that never report one
    (``SttCapabilities.reports_language`` false) leave the whole mechanism
    inert regardless of this policy.
    """

    enabled: bool = False
    #: Consecutive qualifying utterances that must agree before the switch
    #: commits. One borrowed sentence must not flip the call.
    confirm_utterances: int = Field(default=2, ge=1)
    #: Utterances shorter than this many words count neither for nor against a
    #: pending switch: one-word answers ("ja", "no", "okay") are exactly where
    #: language detection is noisiest.
    min_utterance_words: int = Field(default=3, ge=1)


# ---------------------------------------------------------------------------
# Agent, language, call
# ---------------------------------------------------------------------------


class LanguageConfig(BaseModel):
    """What differs for one language.

    Every field is optional: unset means "use the agent's default". The merge in
    :func:`resolve_profile` replaces whole sections, so a language that wants a
    different ceiling supplies a whole :class:`TurnParams`.
    """

    language: str
    voice: str | None = None
    prompts: PromptSet | None = None
    spoken: SpokenPrompts | None = None
    turn: TurnParams | None = None
    fragment: FragmentParams | None = None
    chunking: ChunkingConfig | None = None
    vad: VadConfig | None = None
    stt: SttConfig | None = None
    tts: TtsConfig | None = None
    ttt: TttConfig | None = None
    #: VOAD-27: lets a language (or, via ``CallContext.overrides``, a single
    #: call) replace the agent's whole silence policy — same "whole section,
    #: never half of one" rule as every other field here. None keeps the
    #: agent's default.
    silence: SilencePolicy | None = None


class VoiceAgentConfig(BaseModel):
    """One organization's agent: the defaults every call starts from."""

    name: str = "agent"
    default_language: str = "en"

    stt: SttConfig
    tts: TtsConfig
    ttt: TttConfig
    vad: VadConfig = Field(default_factory=VadConfig)

    prompts: PromptSet
    spoken: SpokenPrompts
    turn: TurnParams = Field(default_factory=TurnParams)
    fragment: FragmentParams = Field(default_factory=FragmentParams)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    silence: SilencePolicy = Field(default_factory=SilencePolicy)
    language_switch: LanguageSwitchPolicy = Field(default_factory=LanguageSwitchPolicy)

    #: Per-language overrides, keyed the way callers send language codes.
    languages: dict[str, LanguageConfig] = Field(default_factory=dict)

    #: Hang up a call that has produced no frames for this long. Guards against
    #: a leg that stays open after the far end vanishes.
    idle_timeout_seconds: int = 300
    #: Hard cap on total call length, regardless of activity — distinct from
    #: idle_timeout_seconds above, which only fires on inactivity. None means
    #: no cap.
    max_duration_seconds: int | None = None
    #: Speak first. False waits for the caller, which is what an inbound leg wants.
    greet_first: bool = True

    #: Advertises a "send_sms" function to the model. Off by default: the tool
    #: schema is baked into the LLMContext at call start (prefix-cache rule —
    #: it can never change mid-call), so exposing it is an explicit choice.
    sms_tool_enabled: bool = False
    #: The fixed SMS body (VOAD-60) — the model sees it in the tool's own
    #: description (so it can judge whether sending it now makes sense) but
    #: never composes or edits it. Actually sending is deferred to the end of
    #: the call — see ``src.application.engine.sms_intent.SmsIntent``.
    sms_tool_message: str = ""
    #: VOAD-62: the tool is only offered to the model when this is
    #: ``approved`` — pending (staff-authored, not yet signed off) text is
    #: never sent, never even advertised.
    sms_tool_message_status: SmsMessageStatusEnum = SmsMessageStatusEnum.approved


class CustomerProfile(BaseModel):
    """What is known about this caller before the first frame of audio.

    Rendered into the prompt as its own layer, after the agent's instructions
    and before the conversation, so the cacheable prefix stays stable per
    language while this varies per call.
    """

    customer_id: str = ""
    name: str = ""
    #: The caller's own number, E.164. Populated from ``Client.phone`` — the
    #: only destination the SMS tool is allowed to send to.
    phone: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    offers: list[str] = Field(default_factory=list)


class CallContext(BaseModel):
    """What only this call knows."""

    call_id: str
    org_uuid: str
    agent_id: int | str | None = None
    direction: CallDirectionEnum = CallDirectionEnum.outbound
    #: Language for this call. Falls back to the agent's default.
    language: str | None = None
    customer: CustomerProfile | None = None
    #: The script for this call (already rendered — the engine never templates).
    #: None keeps whatever the prompt layers resolve to.
    call_script: str | None = None
    #: VOAD-68: the callee's own idle timeout; None keeps the agent's.
    idle_timeout_seconds: int | None = None
    #: Per-call overrides, for A/B runs and for support reproducing a complaint.
    #: Same shape as a language row, applied last.
    overrides: LanguageConfig | None = None


class ResolvedProfile(BaseModel):
    """One call's settings after the merge — what the pipeline is built from.

    Deliberately flat. Everything downstream reads this and never the layers it
    came from, so a call's behaviour can be logged, diffed, and replayed as one
    object.
    """

    language: str
    stt: SttConfig
    tts: TtsConfig
    ttt: TttConfig
    vad: VadConfig
    prompts: PromptSet
    spoken: SpokenPrompts
    turn: TurnParams
    fragment: FragmentParams
    chunking: ChunkingConfig
    silence: SilencePolicy
    idle_timeout_seconds: int
    max_duration_seconds: int | None
    greet_first: bool

    def summary(self) -> str:
        """One line for the call log. The first thing to read when a call misbehaves."""
        return (
            f"language={self.language} "
            f"stt={self.stt.adapter}:{self.stt.model.code} "
            f"tts={self.tts.adapter}:{self.tts.voice} "
            f"ttt={self.ttt.adapter}:{self.ttt.model.code} "
            f"vad={self.vad.adapter} turn={self.turn.analyzer}"
            f"(smart={self.turn.smart_turn},max={self.turn.max_delay_ms}ms) "
            f"chunking={self.chunking.mode}"
        )
