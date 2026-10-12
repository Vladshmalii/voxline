"""The voice engine: one call, driven by one organization's configuration.

    from src.application.engine import CallSession, CallContext, resolve_profile

    session = CallSession(agent=agent_config, call=context, transport=transport)
    await session.run()

``agent_config`` is a :class:`VoiceAgentConfig` — a plain pydantic object your
repositories build from the organization's rows. The engine never reads the
environment, never opens a database session, and never imports a vendor module:
recognisers, synthesisers, language models and detectors are resolved by name
through the registries in ``src/integrations``.

What is configurable, and where it lives:

===========================  =========================================
models                       ``SttConfig`` / ``TtsConfig`` / ``TttConfig``
                             — adapter, endpoint, key, model code
protocol behaviour           ``ModelConfig.capabilities`` — minimum buffer,
                             trailing silence, finalize window
turn taking                  ``TurnParams`` — analyzer, min/max delay,
                             repoll, silence fallback
fragments                    ``FragmentParams`` — what a ceiling commit may
                             send to the model
voice activity               ``VadConfig`` — confidence, start/stop, volume
speaking                     ``ChunkingConfig`` — clause vs whole turn,
                             chunk size, loudness matching
what it says                 ``PromptSet`` and ``SpokenPrompts``, per language
silence                      ``SilencePolicy`` — prompt after, hang up after
===========================  =========================================

Every one of them can be set on the agent and overridden per language, and
overridden again per call for an A/B run or to reproduce a complaint.
"""

from src.application.engine.capabilities import (
    SttCapabilities,
    TtsCapabilities,
    TttCapabilities,
)
from src.application.engine.config import (
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
    resolve_profile,
)

# Pipeline and session are resolved on first use rather than imported here.
# They pull in `src.integrations`, whose adapters import back into this package
# for the audio path and the capability types — eager imports would close that
# loop through this module while it is still half-built.
_LAZY: dict[str, str] = {
    "BuiltPipeline": "src.application.engine.pipeline",
    "build_pipeline": "src.application.engine.pipeline",
    "CallSession": "src.application.engine.session",
    "SessionHooks": "src.application.engine.session",
    "LanguageSwitcher": "src.application.engine.language_switch",
    "hot_switch_blockers": "src.application.engine.language_switch",
    "readiness": "src.application.engine.readiness",
}


def __getattr__(name: str):
    """Import the heavy members on first access (PEP 562)."""
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "BuiltPipeline",
    "CallContext",
    "CallSession",
    "ChunkingConfig",
    "CustomerProfile",
    "FragmentParams",
    "LanguageConfig",
    "LanguageSwitchPolicy",
    "LanguageSwitcher",
    "ModelConfig",
    "PromptSet",
    "ProviderConfig",
    "ResolvedProfile",
    "SessionHooks",
    "SilencePolicy",
    "SpokenPrompts",
    "SttCapabilities",
    "SttConfig",
    "TtsCapabilities",
    "TtsConfig",
    "TttCapabilities",
    "TttConfig",
    "TurnParams",
    "VadConfig",
    "VoiceAgentConfig",
    "build_pipeline",
    "hot_switch_blockers",
    "readiness",
    "resolve_profile",
]
