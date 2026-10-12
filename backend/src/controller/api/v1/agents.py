"""Voice-agent resource router: the agent, its languages, and its diagnostics.

The agent accumulates every setting a call starts from, so this router carries
more than CRUD: nested language rows (layer 2 of the engine's merge), a
profile preview ("what would a call in this language actually use"), and
readiness — both running the same code a real call runs, via the services.

Section storage rule (see ``src/schemas/admin.py``): agent sections are stored
``exclude_unset`` so engine defaults keep evolving under untouched knobs;
explicit ``null`` resets a section to ``{}`` (pure engine defaults). Language
sections are whole-or-NULL, matching the engine's whole-section merge.
"""

from fastapi import APIRouter, HTTPException, Query, Response

from src.application.services.agent import (
    AgentLanguageNotFound,
    AgentNotFound,
    AgentService,
    LanguageExists,
)
from src.application.services.model_assignment import guard_model_fields
from src.application.services.voice_preview import (
    PreviewModelNotFound,
    VoicePreviewError,
    VoicePreviewService,
)
from src.common.enums.engine import SmsMessageStatusEnum
from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import (
    CurrentRole,
    FullAccessDep,
    delete_agents,
    requires_sms_moderation,
    sms_moderation,
    view_agents,
    voice_preview_agents,
    write_agents,
)
from src.models.agent import AgentLanguage, VoiceAgent
from src.repositories.agent import AgentLanguageCRUD, VoiceAgentCRUD
from src.schemas import admin
from src.schemas.engine import ResolvedProfile

router = APIRouter(
    prefix="/voice-agents", tags=["voice-agents"], dependencies=[view_agents]
)


#: Fields only a project administrator may set on an agent: telephony and SMS
#: routes, the technical limits, and the conversation-tuning sections.
_ADMIN_ONLY_FIELDS = frozenset(
    {
        "telephony_id",
        "messaging_id",
        "idle_timeout_seconds",
        "max_duration_seconds",
        "tts_sample_rate",
        "turn",
        "fragment",
        "chunking",
        "vad",
        "silence",
        "language_switch",
    }
)


def _guard_route_fields(
    data: admin.SVoiceAgentCreate | admin.SVoiceAgentUpdate, full_access: bool
) -> None:
    if not full_access and data.model_fields_set & _ADMIN_ONLY_FIELDS:
        raise HTTPException(
            status_code=403,
            detail=(
                "Only project administrators can set telephony, SMS routes, "
                "technical limits and conversation tuning"
            ),
        )


# ── agents ────────────────────────────────────────────────────────────────────
@router.get("", response_model=list[admin.SVoiceAgentRead])
async def list_agents(
    session: SessionUserDep,
    is_active: bool | None = Query(None),
    sms_status: SmsMessageStatusEnum | None = Query(
        None, description="VOAD-62: filter by SMS-tool text moderation status."
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items = await AgentService(session).list(
        is_active=is_active, sms_status=sms_status, limit=limit, offset=offset
    )
    return [
        admin.SVoiceAgentRead.model_validate(i, from_attributes=True) for i in items
    ]


@router.post(
    "",
    response_model=admin.SVoiceAgentDetailsRead,
    status_code=201,
    dependencies=[write_agents],
)
async def create_agent(
    session: SessionUserCommitDep,
    data: admin.SVoiceAgentCreate,
    role: CurrentRole,
    full_access: FullAccessDep,
):
    guard_model_fields(data, full_access)
    _guard_route_fields(data, full_access)
    obj = await AgentService(session).create(
        data, moderated=requires_sms_moderation(role)
    )
    return admin.SVoiceAgentDetailsRead.model_validate(obj, from_attributes=True)


@router.get("/{item_id}", response_model=admin.SVoiceAgentDetailsRead)
async def get_agent(session: SessionUserDep, item_id: int):
    obj = await VoiceAgentCRUD(session).get_one_or_none(VoiceAgent.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="voice-agent not found")
    return admin.SVoiceAgentDetailsRead.model_validate(obj, from_attributes=True)


@router.patch(
    "/{item_id}",
    response_model=admin.SVoiceAgentDetailsRead,
    dependencies=[write_agents],
)
async def update_agent(
    session: SessionUserCommitDep,
    item_id: int,
    data: admin.SVoiceAgentUpdate,
    role: CurrentRole,
    full_access: FullAccessDep,
):
    guard_model_fields(data, full_access)
    _guard_route_fields(data, full_access)
    try:
        obj = await AgentService(session).update(
            item_id, data, moderated=requires_sms_moderation(role)
        )
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")
    return admin.SVoiceAgentDetailsRead.model_validate(obj, from_attributes=True)


@router.delete("/{item_id}", status_code=204, dependencies=[delete_agents])
async def delete_agent(session: SessionUserCommitDep, item_id: int):
    if not await VoiceAgentCRUD(session).delete(VoiceAgent.id == item_id):
        raise HTTPException(status_code=404, detail="voice-agent not found")


# ── SMS moderation (VOAD-62) ─────────────────────────────────────────────────
@router.post(
    "/{item_id}/sms-moderation/approve",
    response_model=admin.SVoiceAgentDetailsRead,
    dependencies=[sms_moderation],
)
async def approve_agent_sms(session: SessionUserCommitDep, item_id: int):
    try:
        obj = await AgentService(session).approve_sms(item_id)
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")
    return admin.SVoiceAgentDetailsRead.model_validate(obj, from_attributes=True)


@router.post(
    "/{item_id}/sms-moderation/reject",
    response_model=admin.SVoiceAgentDetailsRead,
    dependencies=[sms_moderation],
)
async def reject_agent_sms(session: SessionUserCommitDep, item_id: int):
    """Rejected text is cleared, not left pending forever — the tool has
    nothing to send until staff writes a new message, which starts a fresh
    round of moderation."""
    try:
        obj = await AgentService(session).reject_sms(item_id)
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")
    return admin.SVoiceAgentDetailsRead.model_validate(obj, from_attributes=True)


# ── languages (layer 2) ───────────────────────────────────────────────────────
@router.get("/{item_id}/languages", response_model=list[admin.SAgentLanguageRead])
async def list_agent_languages(session: SessionUserDep, item_id: int):
    try:
        items = await AgentService(session).languages(item_id)
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")
    return [
        admin.SAgentLanguageRead.model_validate(i, from_attributes=True) for i in items
    ]


@router.post(
    "/{item_id}/languages",
    response_model=admin.SAgentLanguageRead,
    status_code=201,
    dependencies=[write_agents],
)
async def create_agent_language(
    session: SessionUserCommitDep,
    item_id: int,
    data: admin.SAgentLanguageCreate,
    full_access: FullAccessDep,
):
    guard_model_fields(data, full_access)
    try:
        obj = await AgentService(session).create_language(item_id, data)
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")
    except LanguageExists as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return admin.SAgentLanguageRead.model_validate(obj, from_attributes=True)


@router.patch(
    "/{item_id}/languages/{language_id}",
    response_model=admin.SAgentLanguageRead,
    dependencies=[write_agents],
)
async def update_agent_language(
    session: SessionUserCommitDep,
    item_id: int,
    language_id: int,
    data: admin.SAgentLanguageUpdate,
    full_access: FullAccessDep,
):
    guard_model_fields(data, full_access)
    try:
        obj = await AgentService(session).update_language(item_id, language_id, data)
    except AgentLanguageNotFound:
        raise HTTPException(status_code=404, detail="agent language not found")
    return admin.SAgentLanguageRead.model_validate(obj, from_attributes=True)


@router.delete(
    "/{item_id}/languages/{language_id}", status_code=204, dependencies=[delete_agents]
)
async def delete_agent_language(
    session: SessionUserCommitDep, item_id: int, language_id: int
):
    deleted = await AgentLanguageCRUD(session).delete(
        AgentLanguage.id == language_id, AgentLanguage.agent_id == item_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="agent language not found")


# ── diagnostics ───────────────────────────────────────────────────────────────
@router.get("/{item_id}/profile", response_model=ResolvedProfile)
async def preview_profile(
    session: SessionUserDep, item_id: int, language: str | None = None
):
    """The exact profile a call in `language` would run with — before any call."""
    try:
        return await AgentService(session).resolve_preview(item_id, language)
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")


@router.get("/{item_id}/readiness", response_model=admin.SReadinessRead)
async def agent_readiness(
    session: SessionUserDep,
    item_id: int,
    language: str | None = None,
    probe: bool = Query(True, description="Also reach out to the model servers"),
):
    """Can this agent take a call right now? Misconfiguration surfaces here."""
    try:
        return await AgentService(session).readiness(
            item_id, language=language, probe=probe
        )
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")


@router.post("/preview-voice-direct", dependencies=[voice_preview_agents])
async def preview_voice_direct(
    session: SessionUserDep,
    data: admin.SDirectVoicePreviewRequest,
    full_access: FullAccessDep,
):
    """Synthesizes sample audio directly for a given voice and model/adapter without needing an agent."""
    if not full_access and data.model_fields_set & {"model_id", "adapter"}:
        raise HTTPException(
            403, "Only project administrators can choose a preview model"
        )
    try:
        audio_bytes, media_type = await VoicePreviewService(session).preview_direct(
            data, default_only=not full_access
        )
    except PreviewModelNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except VoicePreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return Response(content=audio_bytes, media_type=media_type)


@router.post("/{item_id}/preview-voice", dependencies=[voice_preview_agents])
async def preview_voice(
    session: SessionUserDep,
    item_id: int,
    data: admin.SVoicePreviewRequest | None = None,
    language: str | None = Query(None),
    text: str | None = Query(None),
):
    """Synthesizes sample audio for this agent's voice settings.

    Accepts options either as JSON body or Query params.
    """
    req_lang = (data.language if data and data.language else language) or None
    req_text = (data.text if data and data.text else text) or None

    try:
        audio_bytes, media_type = await AgentService(session).preview_voice(
            item_id, text=req_text, language=req_lang
        )
    except AgentNotFound:
        raise HTTPException(status_code=404, detail="voice-agent not found")
    except VoicePreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return Response(content=audio_bytes, media_type=media_type)
