"""Agent repositories, and the mapping that turns rows into the engine's input.

``build_agent_config`` is this service's version of the chat service's
``S*Cache`` pattern: the one place where ORM rows become the plain pydantic
configuration everything downstream runs on. The engine never sees a row; a
test never needs a database — both facts depend on this boundary staying here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from src.models.agent import AgentLanguage, VoiceAgent
from src.models.provider import Model
from src.repositories.base import CRUD
from src.schemas.engine import (
    ChunkingConfig,
    FragmentParams,
    LanguageConfig,
    LanguageSwitchPolicy,
    ModelConfig,
    PromptSet,
    ProviderConfig,
    SilencePolicy,
    SpokenPrompts,
    SttConfig,
    TtsConfig,
    TttConfig,
    TurnParams,
    VadConfig,
    VoiceAgentConfig,
)


def _model_config(row: Model) -> ModelConfig:
    return ModelConfig(
        code=row.code,
        capabilities=row.capabilities,
        provider=ProviderConfig(
            url=row.provider.url,
            api_key=row.provider.api_key,
            options=row.provider.options,
        ),
    )


def build_analysis_config(row: Model) -> TttConfig:
    """The organization's analysis model (``Model.is_analysis``) as a ``TttConfig``.

    Only the binding: analysis sends its own sampling
    (``services/analysis.py``), so no agent's ``ttt_*`` knobs apply to it.
    """
    return TttConfig(adapter=row.adapter, model=_model_config(row))


def _language_config(row: AgentLanguage, agent: VoiceAgent) -> LanguageConfig:
    """One language row as the engine's second layer.

    Sections the row leaves NULL stay unset — ``resolve_profile`` falls back
    to the agent. A per-language model binding becomes a *whole* kind section,
    with its params dict on top and the agent's scalars as the fallback, so a
    language that only re-routes the recogniser still ships a complete
    ``SttConfig``.
    """
    sections: dict[str, Any] = {}
    if row.prompts is not None:
        sections["prompts"] = PromptSet(**row.prompts)
    if row.spoken is not None:
        sections["spoken"] = SpokenPrompts(**row.spoken)
    if row.turn is not None:
        sections["turn"] = TurnParams(**row.turn)
    if row.fragment is not None:
        sections["fragment"] = FragmentParams(**row.fragment)
    if row.chunking is not None:
        sections["chunking"] = ChunkingConfig(**row.chunking)
    if row.vad is not None:
        sections["vad"] = VadConfig(**row.vad)

    if row.stt_model is not None:
        params = row.stt_params or {}
        sections["stt"] = SttConfig(
            adapter=row.stt_model.adapter,
            model=_model_config(row.stt_model),
            language=params.get("language", row.language),
        )
    if row.tts_model is not None:
        params = row.tts_params or {}
        sections["tts"] = TtsConfig(
            adapter=row.tts_model.adapter,
            model=_model_config(row.tts_model),
            voice=params.get("voice") or row.voice or agent.tts_voice,
            language=params.get("language", row.language),
            sample_rate=params.get("sample_rate", agent.tts_sample_rate),
            speed=params.get("speed", agent.tts_speed),
            instructions=params.get("instructions", agent.tts_instructions),
        )
    if row.ttt_model is not None:
        params = row.ttt_params or {}
        sections["ttt"] = TttConfig(
            adapter=row.ttt_model.adapter,
            model=_model_config(row.ttt_model),
            temperature=params.get("temperature", agent.ttt_temperature),
            top_p=params.get("top_p", agent.ttt_top_p),
            max_tokens=params.get("max_tokens", agent.ttt_max_tokens),
            enable_thinking=params.get("enable_thinking", agent.ttt_enable_thinking),
            extra_body=params.get("extra_body", agent.ttt_extra_body),
        )

    return LanguageConfig(language=row.language, voice=row.voice, **sections)


def build_agent_config(row: VoiceAgent) -> VoiceAgentConfig:
    """The agent row (with its languages) as the engine's first layer.

    Requires the row's relationships loaded — models are joined-eager and
    languages selectin-eager on the mappers, so anything fetched through
    :class:`VoiceAgentCRUD` qualifies.

    Args:
        row: The agent, relationships loaded.

    Returns:
        The engine's ``VoiceAgentConfig``, validated — a bad row fails here,
        naming the value, not thirty seconds into a customer call.
    """
    return VoiceAgentConfig(
        name=row.name,
        default_language=row.default_language,
        greet_first=row.greet_first,
        idle_timeout_seconds=row.idle_timeout_seconds,
        max_duration_seconds=row.max_duration_seconds,
        sms_tool_enabled=row.sms_tool_enabled,
        sms_tool_message=row.sms_tool_message,
        sms_tool_message_status=row.sms_tool_message_status,
        stt=SttConfig(
            adapter=row.stt_model.adapter,
            model=_model_config(row.stt_model),
            language=row.stt_language,
        ),
        tts=TtsConfig(
            adapter=row.tts_model.adapter,
            model=_model_config(row.tts_model),
            voice=row.tts_voice,
            sample_rate=row.tts_sample_rate,
            speed=row.tts_speed,
            instructions=row.tts_instructions,
        ),
        ttt=TttConfig(
            adapter=row.ttt_model.adapter,
            model=_model_config(row.ttt_model),
            temperature=row.ttt_temperature,
            top_p=row.ttt_top_p,
            max_tokens=row.ttt_max_tokens,
            enable_thinking=row.ttt_enable_thinking,
            extra_body=row.ttt_extra_body,
        ),
        vad=VadConfig(**row.vad),
        prompts=PromptSet(
            system_prompt=row.system_prompt,
            greeting_kickoff=row.greeting_kickoff,
        ),
        spoken=SpokenPrompts(
            silence=row.spoken_silence,
            reprompt=row.spoken_reprompt,
            goodbye=row.spoken_goodbye,
            no_answer=row.spoken_no_answer,
            feedback_request=row.spoken_feedback_request,
        ),
        turn=TurnParams(**row.turn),
        fragment=FragmentParams(**row.fragment),
        chunking=ChunkingConfig(**row.chunking),
        silence=SilencePolicy(**row.silence),
        language_switch=LanguageSwitchPolicy(**row.language_switch),
        languages={
            language.language: _language_config(language, row)
            for language in row.languages
        },
    )


class VoiceAgentCRUD(CRUD[VoiceAgent]):
    model = VoiceAgent

    async def get_config(self, agent_id: int) -> VoiceAgentConfig | None:
        """Fetch an agent and hand back the engine's configuration for it.

        Returns:
            The config, or None when the agent does not exist.
        """
        row = await self.get_one_or_none(VoiceAgent.id == agent_id)
        return build_agent_config(row) if row is not None else None

    async def total_count(self) -> int:
        """Every agent, active or not (VOAD-38 dashboard) — ``GET /voice-agents``
        itself has no count, only a plain list."""
        result = await self.session.execute(
            select(func.count()).select_from(VoiceAgent)
        )
        return result.scalar_one()

    async def active_count(self) -> int:
        """Agents with ``is_active`` set (dashboard)."""
        result = await self.session.execute(
            select(func.count())
            .select_from(VoiceAgent)
            .where(VoiceAgent.is_active.is_(True))
        )
        return result.scalar_one()


class AgentLanguageCRUD(CRUD[AgentLanguage]):
    model = AgentLanguage
