"""Agent-level operations that are more than a row read.

Writes store sections the way the router's docstring promises (agent
sections sparse, language sections whole-or-NULL) and settle VOAD-62's SMS
moderation status. The previews and readiness answer the operator question
"what will a call to this agent actually do" — by running the *same* code a
call runs (``build_agent_config`` → ``resolve_profile`` → the engine's
readiness checks), not a parallel reimplementation that could drift.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.engine.config import CallContext, ResolvedProfile, resolve_profile
from src.application.engine.readiness import readiness
from src.application.services.model_assignment import validate_bindings
from src.application.services.voice_preview import VoicePreviewService
from src.common.enums.engine import SmsMessageStatusEnum
from src.models.agent import AgentLanguage, VoiceAgent
from src.repositories.agent import AgentLanguageCRUD, VoiceAgentCRUD
from src.schemas import admin

#: JSONB section columns on the agent row (non-nullable; {} = engine defaults).
_AGENT_SECTIONS = ("turn", "fragment", "chunking", "vad", "silence", "language_switch")
#: JSONB section columns on a language row (nullable; NULL = inherit).
_LANGUAGE_SECTIONS = ("prompts", "spoken", "turn", "fragment", "chunking", "vad")


class AgentNotFound(LookupError):
    """The agent id resolves to no row in this organization."""


class AgentLanguageNotFound(LookupError):
    """The language id resolves to no row on this agent."""


class LanguageExists(ValueError):
    """The agent already has a row for this language."""


def _derive_default_language(payload: dict) -> None:
    """VOAD-69: the agent's default language always follows its STT
    configuration; it is not an input of the agent API."""
    stt_language = payload.get("stt_language")
    if not stt_language:
        return
    base = stt_language.split("-")[0].strip().lower()
    if base and base != "multi":
        payload["default_language"] = base


def _apply_sms_moderation(payload: dict, moderated: bool) -> None:
    """VOAD-62: decide ``sms_tool_message_status`` from who is writing
    ``sms_tool_message`` — mutates ``payload`` in place, no-op when the
    message isn't part of this write at all (an update that touches other
    fields only).

    Blank text needs no sign-off (there is nothing to review, and the engine
    already refuses to offer the tool with a blank message either way).
    """
    if "sms_tool_message" not in payload:
        return
    message = payload["sms_tool_message"] or ""
    payload["sms_tool_message_status"] = (
        SmsMessageStatusEnum.pending
        if message and moderated
        else SmsMessageStatusEnum.approved
    ).value


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        is_active: bool | None = None,
        sms_status: SmsMessageStatusEnum | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[VoiceAgent]:
        clauses = [VoiceAgent.is_active == is_active] if is_active is not None else []
        if sms_status is not None:
            clauses.append(VoiceAgent.sms_tool_message_status == sms_status)
        return await VoiceAgentCRUD(self.session).get_many_ordered(
            *clauses, limit=limit, offset=offset
        )

    async def create(
        self, data: admin.SVoiceAgentCreate, *, moderated: bool
    ) -> VoiceAgent:
        """Create an agent; unset model bindings get the organization's defaults,
        and the technical knobs (idle timeout, call cap, telephony, TTS rate)
        the organization's agent settings.

        Args:
            data: The agent.
            moderated: Whether text this writer authors needs sign-off (VOAD-62).

        Returns:
            The agent, with its languages loaded.
        """
        payload = data.model_dump(mode="json")
        _derive_default_language(payload)
        await validate_bindings(self.session, payload, create=True)
        # Sections are stored sparse: only the knobs the operator actually set,
        # so engine defaults keep evolving under untouched ones.
        for key in _AGENT_SECTIONS:
            section = getattr(data, key)
            payload[key] = (
                section.model_dump(exclude_unset=True, mode="json")
                if section is not None
                else {}
            )
        _apply_sms_moderation(payload, moderated)
        repo = VoiceAgentCRUD(self.session)
        created = await repo.create(payload)
        # Re-fetch so the eager loaders run: the flushed instance has no
        # `languages` loaded, and validating it would lazy-load outside the
        # async context (MissingGreenlet).
        return await repo.get_one_or_none(VoiceAgent.id == created.id)

    async def update(
        self, agent_id: int, data: admin.SVoiceAgentUpdate, *, moderated: bool
    ) -> VoiceAgent:
        """Apply the fields ``data`` sets; an explicit null section resets it to ``{}``.

        Raises:
            AgentNotFound: If the agent does not exist.
        """
        payload = data.model_dump(exclude_unset=True, mode="json")
        _derive_default_language(payload)
        await validate_bindings(self.session, payload)
        for key in _AGENT_SECTIONS:
            if key in payload:
                section = getattr(data, key)
                payload[key] = (
                    section.model_dump(exclude_unset=True, mode="json")
                    if section is not None
                    else {}
                )
        _apply_sms_moderation(payload, moderated)
        repo = VoiceAgentCRUD(self.session)
        if payload and not await repo.update(VoiceAgent.id == agent_id, data=payload):
            raise AgentNotFound(agent_id)
        agent = await repo.get_one_or_none(VoiceAgent.id == agent_id)
        if agent is None:
            raise AgentNotFound(agent_id)
        return agent

    async def approve_sms(self, agent_id: int) -> VoiceAgent:
        """VOAD-62: sign off on the agent's SMS-tool text.

        Raises:
            AgentNotFound: If the agent does not exist.
        """
        return await self._set_sms(
            agent_id, {"sms_tool_message_status": SmsMessageStatusEnum.approved.value}
        )

    async def reject_sms(self, agent_id: int) -> VoiceAgent:
        """Rejected text is cleared, not left pending forever — the tool has
        nothing to send until staff writes a new message, which starts a fresh
        round of moderation.

        Raises:
            AgentNotFound: If the agent does not exist.
        """
        return await self._set_sms(
            agent_id,
            {
                "sms_tool_message": "",
                "sms_tool_message_status": SmsMessageStatusEnum.approved.value,
            },
        )

    async def _set_sms(self, agent_id: int, data: dict[str, Any]) -> VoiceAgent:
        repo = VoiceAgentCRUD(self.session)
        if not await repo.update(VoiceAgent.id == agent_id, data=data):
            raise AgentNotFound(agent_id)
        return await repo.get_one_or_none(VoiceAgent.id == agent_id)

    async def languages(self, agent_id: int) -> list[AgentLanguage]:
        """The agent's language rows (layer 2 of the engine's merge).

        Raises:
            AgentNotFound: If the agent does not exist.
        """
        if not await VoiceAgentCRUD(self.session).exists(VoiceAgent.id == agent_id):
            raise AgentNotFound(agent_id)
        return await AgentLanguageCRUD(self.session).get_many_ordered(
            AgentLanguage.agent_id == agent_id
        )

    async def create_language(
        self, agent_id: int, data: admin.SAgentLanguageCreate
    ) -> AgentLanguage:
        """Add a language row; its sections are stored whole.

        Raises:
            AgentNotFound: If the agent does not exist.
            LanguageExists: If the agent already configures this language.
        """
        if not await VoiceAgentCRUD(self.session).exists(VoiceAgent.id == agent_id):
            raise AgentNotFound(agent_id)
        payload = data.model_dump(exclude_unset=True, mode="json")
        await validate_bindings(self.session, payload, language=True)
        for key in _LANGUAGE_SECTIONS:
            section = getattr(data, key)
            if section is not None:
                payload[key] = section.model_dump(exclude_unset=True, mode="json")
        try:
            return await AgentLanguageCRUD(self.session).create(
                {**payload, "agent_id": agent_id}
            )
        except IntegrityError:
            # One row per language per agent; "which row won" must never be a question.
            raise LanguageExists(f"language {data.language!r} already configured")

    async def update_language(
        self, agent_id: int, language_id: int, data: admin.SAgentLanguageUpdate
    ) -> AgentLanguage:
        """Apply the fields ``data`` sets; an explicit null section inherits again.

        Raises:
            AgentLanguageNotFound: If the agent has no such language row.
        """
        payload = data.model_dump(exclude_unset=True, mode="json")
        await validate_bindings(self.session, payload, language=True)
        for key in _LANGUAGE_SECTIONS:
            if key in payload:
                section = getattr(data, key)
                payload[key] = (
                    section.model_dump(exclude_unset=True, mode="json")
                    if section is not None
                    else None  # explicit null = back to inheriting the agent's
                )
        repo = AgentLanguageCRUD(self.session)
        clauses = (AgentLanguage.id == language_id, AgentLanguage.agent_id == agent_id)
        if payload and not await repo.update(*clauses, data=payload):
            raise AgentLanguageNotFound(language_id)
        language = await repo.get_one_or_none(*clauses)
        if language is None:
            raise AgentLanguageNotFound(language_id)
        return language

    async def preview_voice(
        self, agent_id: int, *, text: str | None = None, language: str | None = None
    ) -> tuple[bytes, str]:
        """Sample audio in the voice a call in ``language`` would speak with.

        Returns:
            ``(audio_bytes, media_type)``.

        Raises:
            AgentNotFound: If the agent does not exist.
            VoicePreviewError: If the synthesiser refused or was unreachable.
        """
        profile = await self.resolve_preview(agent_id, language)
        return await VoicePreviewService().preview(
            profile.tts, text=text, language=language
        )

    async def resolve_preview(
        self, agent_id: int, language: str | None = None
    ) -> ResolvedProfile:
        """The profile a call to this agent would run with, without a call.

        The same two-row answer a support engineer reconstructs after a
        complaint, available before the complaint.

        Args:
            agent_id: The agent.
            language: Optional call language; defaults to the agent's.

        Returns:
            The resolved profile.

        Raises:
            AgentNotFound: If the agent does not exist.
        """
        config = await VoiceAgentCRUD(self.session).get_config(agent_id)
        if config is None:
            raise AgentNotFound(agent_id)
        context = CallContext(call_id="preview", org_uuid="preview", language=language)
        return resolve_profile(config, context)

    async def readiness(
        self, agent_id: int, *, language: str | None = None, probe: bool = True
    ) -> dict[str, Any]:
        """Can this agent take a call right now?

        A wrong endpoint or an expired key surfaces here, at configuration
        time — not as a customer listening to silence.

        Args:
            agent_id: The agent.
            language: Optional language to check the profile of.
            probe: Whether to reach out to the model servers; False keeps the
                check local and fast.

        Returns:
            ``{"ready": bool, "checks": [...]}`` — the shape the platform's
            readiness endpoints already speak.

        Raises:
            AgentNotFound: If the agent does not exist.
        """
        config = await VoiceAgentCRUD(self.session).get_config(agent_id)
        if config is None:
            raise AgentNotFound(agent_id)
        context = CallContext(
            call_id="readiness", org_uuid="readiness", language=language
        )
        profile = resolve_profile(config, context)
        return await readiness(profile, agent=config, probe=probe)
