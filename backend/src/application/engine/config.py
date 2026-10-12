"""The engine's input contract, and the merge that resolves it.

The pydantic schemas themselves live in :mod:`src.schemas.engine` (every
schema in the platform lives under ``src/schemas``); this module re-exports
them unchanged and owns what makes them an engine: :func:`resolve_profile`,
the one-level-deep merge of agent -> language -> per-call overrides, and
:func:`hot_switch_blockers`, the rule for what a live call may switch to.
Import from here inside the engine; the re-export keeps every existing import
site (adapters, tests, pipeline) working and the engine reading one module.
"""

from __future__ import annotations

from typing import Any, Literal

from src.common.enums.engine import CallDirectionEnum
from src.schemas.engine import (
    CallContext,
    ChunkingConfig,
    CustomerProfile,
    FragmentParams,
    LanguageConfig,
    LanguageSwitchPolicy,
    ModelConfig,
    PromptSet,
    ProviderConfig,
    ResolvedProfile,
    SilencePolicy,
    SpokenPrompts,
    SttConfig,
    TtsConfig,
    TttConfig,
    TurnParams,
    VadConfig,
    VoiceAgentConfig,
)

__all__ = [
    "CallContext",
    "ChunkingConfig",
    "CustomerProfile",
    "FragmentParams",
    "LanguageConfig",
    "LanguageSwitchPolicy",
    "ModelConfig",
    "PromptSet",
    "ProviderConfig",
    "ResolvedProfile",
    "SilencePolicy",
    "SpokenPrompts",
    "SttConfig",
    "TtsConfig",
    "TttConfig",
    "TurnParams",
    "VadConfig",
    "VoiceAgentConfig",
    "hot_switch_blockers",
    "match_language",
    "resolve_profile",
]


def match_language(
    available: dict[str, LanguageConfig], language: str | None
) -> str | None:
    """Resolve a language code against the configured ones.

    Full code first (``pt-br``), then the base subtag (``pt``). Returns None
    when neither is configured, which the caller reads as "use the defaults".

    Args:
        available: Configured languages, keyed by code.
        language: The code to resolve, or None.

    Returns:
        The matching key, or None.
    """
    if not language:
        return None
    code = language.strip().lower().replace("_", "-")
    if code in available:
        return code
    base = code.split("-")[0]
    return base if base in available else None


def resolve_profile(agent: VoiceAgentConfig, context: CallContext) -> ResolvedProfile:
    """Merge agent, language and call overrides into the profile a call runs with.

    Args:
        agent: The organization's agent configuration.
        context: This call's context, including any per-call override.

    Returns:
        The flattened settings for this call.
    """
    requested = context.language or agent.default_language
    key = match_language(agent.languages, requested)
    language_config = agent.languages.get(key) if key else None
    layers = [
        layer for layer in (language_config, context.overrides) if layer is not None
    ]

    def pick(field: str, default: Any) -> Any:
        for layer in reversed(layers):
            value = getattr(layer, field, None)
            if value is not None:
                return value
        return default

    tts = pick("tts", agent.tts)
    voice = pick("voice", None)
    if voice and voice != tts.voice:
        tts = tts.model_copy(update={"voice": voice})

    language = (language_config.language if language_config else requested).lower()
    stt = pick("stt", agent.stt)
    if stt.language is None:
        stt = stt.model_copy(update={"language": language})
    if tts.language is None:
        tts = tts.model_copy(update={"language": language})

    prompts = pick("prompts", agent.prompts)
    if context.call_script is not None:
        prompts = prompts.model_copy(update={"call_script": context.call_script})

    return ResolvedProfile(
        language=language,
        stt=stt,
        tts=tts,
        ttt=pick("ttt", agent.ttt),
        vad=pick("vad", agent.vad),
        prompts=prompts,
        spoken=pick("spoken", agent.spoken),
        turn=pick("turn", agent.turn),
        fragment=pick("fragment", agent.fragment),
        chunking=pick("chunking", agent.chunking),
        # VOAD-27: was `agent.silence` unconditionally — silence policy (incl.
        # the reset/feedback timeouts) now merges through the same
        # language -> call-override chain as every other section, so a
        # language or a per-call override can replace it, consistent with
        # `hot_switch_blockers` never checking it (it's hot-appliable, same
        # as prompts/spoken/turn).
        silence=pick("silence", agent.silence),
        idle_timeout_seconds=context.idle_timeout_seconds
        or agent.idle_timeout_seconds,
        max_duration_seconds=agent.max_duration_seconds,
        greet_first=agent.greet_first
        and context.direction == CallDirectionEnum.outbound,
    )


def hot_switch_blockers(active: ResolvedProfile, new: ResolvedProfile) -> list[str]:
    """What stops `active` from becoming `new` without rebuilding the pipeline.

    Pure, and deliberately here rather than next to the language switcher:
    readiness (and through it the HTTP process) asks the same question the
    switcher asks live, and must be able to without importing the pipeline
    stack. Every service is constructed once per call, so anything baked into
    a constructor is a blocker; the hot-appliable remainder — prompts, spoken
    lines, turn timing, fragment vocabulary, the voice, the language tags — is
    deliberately not checked here.

    Args:
        active: The profile the call is running with.
        new: The profile the target language resolves to.

    Returns:
        Human-readable blockers, empty when the switch can be applied live.
    """
    blockers: list[str] = []

    if (active.stt.adapter, active.stt.model) != (new.stt.adapter, new.stt.model):
        blockers.append(
            f"stt {active.stt.adapter}:{active.stt.model.code} → "
            f"{new.stt.adapter}:{new.stt.model.code} (recogniser is built once per call)"
        )

    same_tts_backend = (
        active.tts.adapter == new.tts.adapter
        and active.tts.model == new.tts.model
        and active.tts.sample_rate == new.tts.sample_rate
        and active.tts.speed == new.tts.speed
        and active.tts.instructions == new.tts.instructions
    )
    if not same_tts_backend:
        blockers.append(
            f"tts {active.tts.adapter}:{active.tts.model.code} → "
            f"{new.tts.adapter}:{new.tts.model.code} (only the voice can change mid-call)"
        )

    if active.ttt != new.ttt:
        blockers.append(
            f"ttt {active.ttt.adapter}:{active.ttt.model.code} → "
            f"{new.ttt.adapter}:{new.ttt.model.code} (LLM client is built once per call)"
        )

    if active.vad != new.vad:
        blockers.append("vad settings differ (the detector is built once per call)")

    if active.chunking != new.chunking:
        blockers.append("chunking differs (the TTS aggregator is built once per call)")

    return blockers


#: Frames the transport moves. 16 kHz in, whatever the TTS emits out; the
#: telephony leg is 8 kHz µ-law and is converted in one place (`engine/audio.py`).
AudioFormat = Literal["pcm16"]
