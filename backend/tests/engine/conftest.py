"""Fixtures for the engine tests. No database, no network, no environment.

The engine takes plain pydantic configuration, which is what makes this
possible: a test builds the same object a repository would, and every code path
below it is the one a real call runs.
"""

from __future__ import annotations

import pytest

# The engine suite runs in the interpreter that has pipecat (research/.venv);
# in the project venv the whole directory skips instead of erroring.
pytest.importorskip("pipecat", reason="engine tests need the pipecat interpreter")

from src.application.engine.config import (
    ChunkingConfig,
    FragmentParams,
    LanguageConfig,
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
from src.common.enums.engine import SttAdapterEnum, TtsAdapterEnum, TttAdapterEnum


def make_model(
    code: str = "test-model", url: str = "http://127.0.0.1:59100/v1", **caps
) -> ModelConfig:
    """A model row pointing at a port nothing listens on.

    Deliberately unreachable: a unit test that accidentally opens a connection
    should fail fast rather than reach a real service.
    """
    return ModelConfig(
        code=code,
        provider=ProviderConfig(url=url, api_key="not-needed"),
        capabilities=caps,
    )


def make_agent(**overrides) -> VoiceAgentConfig:
    """A complete agent, with every section at its default unless overridden."""
    defaults = {
        "name": "test-agent",
        "default_language": "en",
        "stt": SttConfig(
            adapter=SttAdapterEnum.qwen3_asr,
            model=make_model("test-asr", "ws://127.0.0.1:59101/v1/realtime"),
        ),
        "tts": TtsConfig(
            adapter=TtsAdapterEnum.qwen3_tts,
            voice="test-voice",
            model=make_model("test-tts", "http://127.0.0.1:59102/v1"),
        ),
        "ttt": TttConfig(
            adapter=TttAdapterEnum.openai_compatible,
            model=make_model("test-llm"),
        ),
        "prompts": PromptSet(
            system_prompt="You are a voice agent.",
            call_script="Greet, help, close.",
            greeting_kickoff="Open the conversation.",
        ),
        "spoken": SpokenPrompts(
            silence="Are you still there?",
            reprompt="Sorry, go ahead.",
            goodbye="Goodbye.",
        ),
    }
    defaults.update(overrides)
    return VoiceAgentConfig(**defaults)


def make_profile(
    language: str = "en",
    *,
    smart_turn: bool = True,
    min_delay_ms: int = 200,
    max_delay_ms: int = 3000,
    repoll_ms: int = 400,
    silence_fallback_ms: int = 1100,
    transcript_timeout_ms: int = 3000,
    min_words: int = 2,
    dangling_tokens: tuple[str, ...] = ("and", "but", "my", "the", "because", "to"),
    complete_short: tuple[str, ...] = ("yes", "no", "hello"),
) -> ResolvedProfile:
    """A resolved profile, the way the pipeline sees one."""
    agent = make_agent()
    return ResolvedProfile(
        language=language,
        stt=agent.stt,
        tts=agent.tts,
        ttt=agent.ttt,
        vad=VadConfig(),
        prompts=agent.prompts,
        spoken=agent.spoken,
        turn=TurnParams(
            smart_turn=smart_turn,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
            repoll_ms=repoll_ms,
            silence_fallback_ms=silence_fallback_ms,
            transcript_timeout_ms=transcript_timeout_ms,
        ),
        fragment=FragmentParams(
            min_words=min_words,
            dangling_tokens=frozenset(dangling_tokens),
            complete_short=frozenset(complete_short),
        ),
        chunking=ChunkingConfig(),
        silence=SilencePolicy(),
        idle_timeout_seconds=300,
        max_duration_seconds=None,
        greet_first=True,
    )


def make_language(language: str = "ru", **overrides) -> LanguageConfig:
    """A language row with only the sections a test cares about."""
    return LanguageConfig(language=language, **overrides)


@pytest.fixture
def agent() -> VoiceAgentConfig:
    """A default agent."""
    return make_agent()


@pytest.fixture
def profile() -> ResolvedProfile:
    """A default English profile."""
    return make_profile()
