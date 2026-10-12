"""Pydantic schemas for the admin CRUD API.

Every resource exposes three schemas (same convention as the payment service):

* ``*Create`` — the writable fields required to create a row.
* ``*Update`` — the same fields, all optional (partial update / ``PATCH``).
* ``*Read``   — what the API returns (``id`` + timestamps + domain fields).

The behavioural sections (turn taking, chunking, VAD…) are typed with the
engine's own schemas from :mod:`src.schemas.engine`, not free-form dicts — the
API validates exactly what a call will consume. Two storage rules worth
knowing when reading the routers:

* On the **agent**, sections are stored ``exclude_unset`` so an operator who
  set one knob has set one knob; engine defaults keep evolving underneath.
  Reads return the *effective* section (defaults filled in), which is what a
  configuration UI should display.
* On a **language row**, an unset section is NULL — "inherit the agent's" —
  and a set one replaces the agent's section whole, per the engine's merge.
"""

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
)

from src.common.enums.campaign import (
    CallLifecycleEnum,
    CallOutcomeEnum,
    CampaignStatusEnum,
    ClientSegmentEnum,
    ClientStatusEnum,
    ReasonCategoryEnum,
    SentimentEnum,
)
from src.common.enums.engine import (
    CallDirectionEnum,
    CallStatusEnum,
    MessageStatusEnum,
    ProviderKindEnum,
    SmsMessageStatusEnum,
)
from src.schemas.campaign import CallingHours, RetryPolicy
from src.schemas.engine import (
    ChunkingConfig,
    FragmentParams,
    LanguageConfig,
    LanguageSwitchPolicy,
    PromptSet,
    SilencePolicy,
    SpokenPrompts,
    TurnParams,
    VadConfig,
)


def _none_to_empty(value: Any) -> Any:
    """Read a null JSON section as an empty one.

    ``capabilities`` and ``options`` are NOT NULL columns holding "nothing
    configured" as ``{}``. A client clearing every field in such a section
    naturally sends ``null`` — a form that renders the section as a group of
    inputs has no other way to say "all of them are empty now". Taking that
    literally means a 422 on create and a NOT NULL violation on update, for
    what is the most ordinary edit there is.

    So null is read as ``{}``: the same intent, in the shape the column can
    hold. Absent stays absent — under ``exclude_unset`` an untouched section
    is still left alone, which is what makes a partial update partial.
    """
    return {} if value is None else value


#: A JSON section on a create schema: absent means ``{}``, and so does null.
JsonSection = Annotated[dict, BeforeValidator(_none_to_empty)]

#: The same on an update schema, where the default ``None`` means "not sent"
#: and is dropped by ``exclude_unset``. Defaults are not validated, so that
#: None survives; only a null a client actually sent becomes ``{}``.
OptionalJsonSection = Annotated[dict | None, BeforeValidator(_none_to_empty)]


class _Read(BaseModel):
    """Common read fields shared by every resource."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ── Model provider ────────────────────────────────────────────────────────────
class SModelProviderCreate(BaseModel):
    name: str
    url: str
    api_key: str | None = None
    options: JsonSection = Field(default_factory=dict)


class SModelProviderUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    api_key: str | None = None
    options: OptionalJsonSection = None


class SModelProviderRead(_Read):
    name: str
    url: str
    api_key: str | None
    options: dict


# ── Model ─────────────────────────────────────────────────────────────────────
class SModelCreate(BaseModel):
    name: str
    kind: ProviderKindEnum
    #: A ``*AdapterEnum`` value of the matching kind; the registry rejects an
    #: unknown one at call build time, loudly.
    adapter: str
    code: str
    is_active: bool = False
    is_default: bool = False
    #: Run every agent's post-call analysis on this model (active ``ttt``
    #: only; flagging one clears the previous one).
    is_analysis: bool = False
    capabilities: JsonSection = Field(default_factory=dict)
    provider_id: int


class SModelUpdate(BaseModel):
    name: str | None = None
    adapter: str | None = None
    code: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    is_analysis: bool | None = None
    capabilities: OptionalJsonSection = None
    provider_id: int | None = None


class SModelRead(_Read):
    name: str
    kind: ProviderKindEnum
    adapter: str
    code: str
    is_active: bool
    is_default: bool
    is_analysis: bool
    capabilities: dict
    provider_id: int


class SVoiceRead(BaseModel):
    """One voice from a TTS model's live catalogue (see ``GET /models/{id}/voices``)."""

    id: str
    name: str
    #: Absent when the vendor's catalogue does not carry a language per voice.
    language: str | None = None


# ── Telephony ─────────────────────────────────────────────────────────────────
class STelephonyCreate(BaseModel):
    name: str
    #: A ``TelephonyAdapterEnum`` value; validated by the registry.
    adapter: str
    is_active: bool = False
    account_id: str | None = None
    auth_token: str | None = None
    caller_id: str | None = None
    control_url: str | None = None
    capabilities: JsonSection = Field(default_factory=dict)
    options: JsonSection = Field(default_factory=dict)


class STelephonyUpdate(BaseModel):
    name: str | None = None
    adapter: str | None = None
    is_active: bool | None = None
    account_id: str | None = None
    auth_token: str | None = None
    caller_id: str | None = None
    control_url: str | None = None
    capabilities: OptionalJsonSection = None
    options: OptionalJsonSection = None


class STelephonyRead(_Read):
    name: str
    adapter: str
    is_active: bool
    account_id: str | None
    auth_token: str | None
    caller_id: str | None
    control_url: str | None
    capabilities: dict
    options: dict


# ── Messaging ─────────────────────────────────────────────────────────────────
class SMessagingCreate(BaseModel):
    name: str
    #: A ``MessagingAdapterEnum`` value; validated by the registry.
    adapter: str
    is_active: bool = False
    account_id: str | None = None
    auth_token: str | None = None
    sender: str | None = None
    sender_pool_id: str | None = None
    control_url: str | None = None
    capabilities: JsonSection = Field(default_factory=dict)
    options: JsonSection = Field(default_factory=dict)


class SMessagingUpdate(BaseModel):
    name: str | None = None
    adapter: str | None = None
    is_active: bool | None = None
    account_id: str | None = None
    auth_token: str | None = None
    sender: str | None = None
    sender_pool_id: str | None = None
    control_url: str | None = None
    capabilities: OptionalJsonSection = None
    options: OptionalJsonSection = None


class SMessagingRead(_Read):
    name: str
    adapter: str
    is_active: bool
    account_id: str | None
    auth_token: str | None
    sender: str | None
    sender_pool_id: str | None
    control_url: str | None
    capabilities: dict
    options: dict


class SSmsSend(BaseModel):
    """One outbound SMS."""

    to: str
    body: str = Field(min_length=1, max_length=1600)
    #: Overrides the route's default sender for this message.
    sender: str | None = None
    #: Which messaging row to send through. None uses the organization's
    #: single active route.
    messaging_id: int | None = None


class SMessageRead(_Read):
    """A sent message and wherever the carrier's verdict has got to.

    ``status`` is ``sent`` right after the provider accepts it; delivery
    callbacks move it to ``delivered``, ``undelivered`` or ``failed``
    afterwards, so a caller who needs the verdict re-reads this row.
    """

    uuid: UUID
    messaging_id: int
    call_id: int | None = None
    agent_id: int | None = None
    agent_name: str | None = None
    to_number: str
    sender: str | None
    body: str
    segments: int
    status: MessageStatusEnum
    provider_ref: str | None
    error: str | None
    sent_at: datetime | None
    settled_at: datetime | None


class SMessageListRead(BaseModel):
    data: list[SMessageRead]
    count: int


# ── Voice agent ───────────────────────────────────────────────────────────────
class SVoiceAgentCreate(BaseModel):
    name: str
    description: str = ""
    is_active: bool = False

    idle_timeout_seconds: int = Field(300, ge=10)
    max_duration_seconds: int | None = Field(None, ge=10)

    system_prompt: str
    greeting_kickoff: str = ""

    spoken_silence: str
    spoken_reprompt: str
    spoken_goodbye: str
    spoken_no_answer: str = ""
    spoken_feedback_request: str = ""

    #: Advertises a "send_sms" function to the model, sent only to the
    #: caller's own number.
    sms_tool_enabled: bool = False
    #: The fixed SMS body (VOAD-60) — the model never composes its own text.
    #: Moderation status is computed server-side (VOAD-62), not settable here.
    sms_tool_message: str = ""

    # Behavioural sections. None means "engine defaults"; a provided section is
    # stored sparse (only the knobs the operator actually set).
    turn: TurnParams | None = None
    fragment: FragmentParams | None = None
    chunking: ChunkingConfig | None = None
    vad: VadConfig | None = None
    silence: SilencePolicy | None = None
    language_switch: LanguageSwitchPolicy | None = None

    # Omitted bindings are assigned by the server from organization defaults.
    stt_model_id: int | None = None
    tts_model_id: int | None = None
    ttt_model_id: int | None = None

    stt_language: str | None = None
    tts_voice: str
    tts_sample_rate: int = 24000
    tts_speed: float | None = None
    tts_instructions: str | None = None
    ttt_temperature: float | None = None
    ttt_top_p: float | None = None
    ttt_max_tokens: int | None = None
    ttt_enable_thinking: bool | None = False
    ttt_extra_body: dict = Field(default_factory=dict)

    telephony_id: int | None = None
    #: Which SMS route the in-call ``send_sms`` tool sends through. None uses
    #: the organization's single active route.
    messaging_id: int | None = None


class SVoiceAgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None

    idle_timeout_seconds: int | None = Field(None, ge=10)
    max_duration_seconds: int | None = Field(None, ge=10)

    system_prompt: str | None = None
    greeting_kickoff: str | None = None

    spoken_silence: str | None = None
    spoken_reprompt: str | None = None
    spoken_goodbye: str | None = None
    spoken_no_answer: str | None = None
    spoken_feedback_request: str | None = None

    sms_tool_enabled: bool | None = None
    sms_tool_message: str | None = None

    turn: TurnParams | None = None
    fragment: FragmentParams | None = None
    chunking: ChunkingConfig | None = None
    vad: VadConfig | None = None
    silence: SilencePolicy | None = None
    language_switch: LanguageSwitchPolicy | None = None

    stt_model_id: int | None = None
    tts_model_id: int | None = None
    ttt_model_id: int | None = None

    stt_language: str | None = None
    tts_voice: str | None = None
    tts_sample_rate: int | None = None
    tts_speed: float | None = None
    tts_instructions: str | None = None
    ttt_temperature: float | None = None
    ttt_top_p: float | None = None
    ttt_max_tokens: int | None = None
    ttt_enable_thinking: bool | None = None
    ttt_extra_body: dict | None = None

    telephony_id: int | None = None
    messaging_id: int | None = None


class SVoiceAgentRead(_Read):
    uuid: UUID
    name: str
    description: str
    is_active: bool

    default_language: str
    idle_timeout_seconds: int
    max_duration_seconds: int | None

    system_prompt: str
    greeting_kickoff: str

    spoken_silence: str
    spoken_reprompt: str
    spoken_goodbye: str
    spoken_no_answer: str
    spoken_feedback_request: str

    sms_tool_enabled: bool
    sms_tool_message: str
    #: VOAD-62: 'pending' text cannot be sent — the UI shows "На модерации"
    #: and disables sending until an owner/admin/super_admin approves it.
    sms_tool_message_status: SmsMessageStatusEnum

    # Effective sections: sparse storage validated through the engine models,
    # so a UI sees the values a call would actually run with.
    turn: TurnParams
    fragment: FragmentParams
    chunking: ChunkingConfig
    vad: VadConfig
    silence: SilencePolicy
    language_switch: LanguageSwitchPolicy

    stt_model_id: int
    tts_model_id: int
    ttt_model_id: int

    stt_language: str | None
    tts_voice: str
    tts_sample_rate: int
    tts_speed: float | None
    tts_instructions: str | None
    ttt_temperature: float | None
    ttt_top_p: float | None
    ttt_max_tokens: int | None
    ttt_enable_thinking: bool | None
    ttt_extra_body: dict

    telephony_id: int | None
    messaging_id: int | None


# ── Agent language ────────────────────────────────────────────────────────────
class SAgentLanguageCreate(BaseModel):
    language: str
    voice: str | None = None
    #: Whole sections, per the engine's merge: set one and it replaces the
    #: agent's section entirely; leave it None and the agent's applies.
    prompts: PromptSet | None = None
    spoken: SpokenPrompts | None = None
    turn: TurnParams | None = None
    fragment: FragmentParams | None = None
    chunking: ChunkingConfig | None = None
    vad: VadConfig | None = None

    stt_model_id: int | None = None
    tts_model_id: int | None = None
    ttt_model_id: int | None = None
    stt_params: dict | None = None
    tts_params: dict | None = None
    ttt_params: dict | None = None


class SAgentLanguageUpdate(SAgentLanguageCreate):
    language: str | None = None


class SAgentLanguageRead(_Read):
    agent_id: int
    language: str
    voice: str | None
    prompts: PromptSet | None
    spoken: SpokenPrompts | None
    turn: TurnParams | None
    fragment: FragmentParams | None
    chunking: ChunkingConfig | None
    vad: VadConfig | None
    stt_model_id: int | None
    tts_model_id: int | None
    ttt_model_id: int | None
    stt_params: dict | None
    tts_params: dict | None
    ttt_params: dict | None


class SVoiceAgentDetailsRead(SVoiceAgentRead):
    """Agent plus its language rows — the full layer-1 + layer-2 picture."""

    languages: list[SAgentLanguageRead]


# ── Client ────────────────────────────────────────────────────────────────────
class SClientUpdate(BaseModel):
    name: str | None = None
    status: ClientStatusEnum | None = None
    country: str | None = None
    language: str | None = None
    vip_status: str | None = None
    last_deposit: float | None = None
    last_active: datetime | None = None
    segment: ClientSegmentEnum | None = None
    idle_timeout_seconds: int | None = Field(None, ge=10)


class SClientRead(_Read):
    uuid: UUID
    phone: str
    name: str
    status: ClientStatusEnum
    country: str | None = None
    language: str | None = None
    vip_status: str | None = None
    last_deposit: float | None = None
    last_active: datetime | None = None
    segment: ClientSegmentEnum | None = None
    idle_timeout_seconds: int | None = None
    #: Name(s) of every Audience this client is a member of (VOAD-34) — not a
    #: column on Client itself (membership is many-to-many via
    #: AudienceMember), so the router fills this in with one extra bulk query
    #: per page rather than a per-row join. Empty for a client that only ever
    #: arrived through a campaign's direct contact upload or the segment-only
    #: CSV import with no audience name given.
    audiences: list[str] = Field(default_factory=list)
    #: Count of CallAttempt rows with answered_at set, across all Calls to
    #: this client (VOAD-34) — not a Client column, filled in by the router
    #: with one extra bulk query per page.
    answered_calls: int = 0


class SClientListRead(BaseModel):
    data: list[SClientRead]
    count: int


class SClientImportResult(BaseModel):
    phone: str
    segment: ClientSegmentEnum | None = None
    #: None means the row was accepted.
    error: str | None = None


class SClientImportRead(BaseModel):
    accepted: int
    rejected: int
    results: list[SClientImportResult]


# ── Audience ──────────────────────────────────────────────────────────────────
class SAudienceCreate(BaseModel):
    name: str
    description: str = ""


class SAudienceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_archived: bool | None = None


class SAudienceRead(_Read):
    uuid: UUID
    name: str
    description: str
    is_archived: bool
    member_count: int = 0


class SAudienceListRead(BaseModel):
    data: list[SAudienceRead]
    count: int


class SAudienceMemberRead(_Read):
    uuid: UUID
    client: SClientRead
    language: str | None
    bonuses: list
    player_id: str | None
    vip_status: str | None
    last_deposit: float | None
    last_active: datetime | None
    country: str | None
    timezone: str | None
    attributes: dict


class SAudienceMemberListRead(BaseModel):
    data: list[SAudienceMemberRead]
    count: int


class SAudienceUploadResult(BaseModel):
    phone: str
    member_id: int | None = None
    #: None means the row was accepted and ``member_id`` is set.
    error: str | None = None


class SAudienceUploadRead(BaseModel):
    accepted: int
    rejected: int
    results: list[SAudienceUploadResult]


class SAudienceUploadHistoryRead(_Read):
    """One persisted upload event (VOAD-34's "История загрузок") — distinct
    from :class:`SAudienceUploadRead`, which is the immediate per-request
    result and is never stored."""

    uuid: UUID
    audience_id: int | None
    #: Filled in by the list handler; None when ``audience_id`` is — the
    #: VOAD-32 client import without an ``audience_name``.
    audience_name: str | None = None
    uploaded_by: int
    filename: str
    total_rows: int
    valid_rows: int
    invalid_rows: int


class SAudienceUploadHistoryListRead(BaseModel):
    data: list[SAudienceUploadHistoryRead]
    count: int


# ── Campaign ──────────────────────────────────────────────────────────────────
class SCampaignCreate(BaseModel):
    name: str
    description: str = ""
    agent_id: int
    #: Jinja template; parameters: ``name``, ``bonuses``, ``attributes``.
    call_script: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    calling_hours: CallingHours | None = None
    retry: RetryPolicy | None = None


class SCampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_id: int | None = None
    call_script: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    calling_hours: CallingHours | None = None
    retry: RetryPolicy | None = None
    is_archived: bool | None = None


class SCampaignRead(_Read):
    uuid: UUID
    name: str
    description: str
    status: CampaignStatusEnum
    agent_id: int
    call_script: str
    starts_at: datetime | None
    ends_at: datetime | None
    # Effective sections, defaults filled in — what the dispatcher will use.
    calling_hours: CallingHours
    retry: RetryPolicy
    is_archived: bool


class SCampaignListRead(BaseModel):
    data: list[SCampaignRead]
    count: int


class SReasonCategoryCount(BaseModel):
    reason_category: ReasonCategoryEnum
    count: int


class SCampaignReasonBreakdown(BaseModel):
    total: int
    categories: list[SReasonCategoryCount]


class SCallStatusCount(BaseModel):
    status: CallLifecycleEnum
    count: int


class SCampaignCounters(BaseModel):
    total: int
    #: Messages of this campaign's calls with status sent/delivered.
    sms_sent: int = 0
    by_status: list[SCallStatusCount]


class SCampaignContactRow(BaseModel):
    phone: str
    name: str | None = None
    language: str | None = None
    bonuses: list = Field(default_factory=list)
    player_id: str | None = None
    vip_status: str | None = None
    last_deposit: float | None = None
    last_active: datetime | None = None
    country: str | None = None
    timezone: str | None = None
    attributes: dict = Field(default_factory=dict)


class SCampaignUploadResult(BaseModel):
    phone: str
    call_id: int | None = None
    #: None means the row was accepted and ``call_id`` is set.
    error: str | None = None


class SCampaignUploadRead(BaseModel):
    accepted: int
    rejected: int
    results: list[SCampaignUploadResult]


# ── Call ──────────────────────────────────────────────────────────────────────
#: Fixed v1 tag vocabulary (VOAD-28) — byte-for-byte the same strings as
#: the frontend's CALL_TAG_* constants (CallsPage.jsx). CALL_TAG_FINISHED
#: may also carry a free-text ": <result>" suffix (see validate_call_tag below);
#: any other tag is rejected by SCallTagsUpdate so a bad checkbox value can
#: never reach Call.tags (see also Call.tags's own docstring on the model).
CALL_TAG_NOT_ANSWERED = "Клиент не ответил"
CALL_TAG_ANSWERED = "Клиент ответил"
CALL_TAG_FINISHED = "Разговор завершён"
CALL_TAG_OPTED_OUT = "Отказался от дальнейших звонков"
_CALL_TAG_FIXED = {
    CALL_TAG_NOT_ANSWERED,
    CALL_TAG_ANSWERED,
    CALL_TAG_FINISHED,
    CALL_TAG_OPTED_OUT,
}
_CALL_TAG_FINISHED_PREFIX = f"{CALL_TAG_FINISHED}: "


def validate_call_tag(tag: str) -> bool:
    return tag in _CALL_TAG_FIXED or tag.startswith(_CALL_TAG_FINISHED_PREFIX)


class SCallTagsUpdate(BaseModel):
    tags: list[str]

    @field_validator("tags")
    @classmethod
    def _tags_in_vocabulary(cls, value: list[str]) -> list[str]:
        invalid = [tag for tag in value if not validate_call_tag(tag)]
        if invalid:
            raise ValueError(f"invalid tag(s): {invalid!r}")
        return value


class SCallCreate(BaseModel):
    agent_id: int
    to_number: str
    name: str | None = None
    from_number: str | None = None
    #: Language for this call; falls back to the agent's default.
    language: str | None = None
    bonuses: list = Field(default_factory=list)
    player_id: str | None = None
    vip_status: str | None = None
    last_deposit: float | None = None
    last_active: datetime | None = None
    country: str | None = None
    timezone: str | None = None
    attributes: dict = Field(default_factory=dict)
    #: Per-call overrides — same shape as a language row, applied last. For
    #: A/B runs and support reproducing a complaint.
    overrides: LanguageConfig | None = None


class SCallAttemptRead(_Read):
    uuid: UUID
    call_id: int
    seq: int
    status: CallStatusEnum
    language: str | None
    provider_ref: str | None
    profile_summary: str | None
    summary: str | None
    outcome: CallOutcomeEnum | None
    selected_offer: str | None
    sentiment: SentimentEnum | None
    reason_category: ReasonCategoryEnum | None
    error: str | None
    provider_status: str | None
    provider_reason: str | None
    answered_at: datetime | None
    ended_at: datetime | None

    @computed_field
    @property
    def duration_seconds(self) -> int | None:
        if self.answered_at is None or self.ended_at is None:
            return None
        return max(0, int((self.ended_at - self.answered_at).total_seconds()))


class SCallAttemptDetailsRead(SCallAttemptRead):
    """An attempt with its transcript — what the caller actually heard."""

    messages: list


class SCallAttemptRecordingRead(BaseModel):
    call_id: int
    attempt_id: int
    recording_url: str


class SCallRead(_Read):
    #: Admin/super_admin only — blanked to ``None`` for owner/staff/viewer by
    #: the router (VOAD-28/31); not a resource-level gate, just this field.
    uuid: UUID | None
    client_id: int | None
    #: Populated from the ``Call.client`` join (eager, no extra query) — the
    #: list would otherwise have no dialable number to show at all.
    client: SClientRead | None
    campaign_id: int | None
    agent_id: int | None
    direction: CallDirectionEnum
    status: CallLifecycleEnum
    outcome: CallOutcomeEnum | None
    selected_offer: str | None
    sentiment: SentimentEnum | None
    reason_category: ReasonCategoryEnum | None
    from_number: str | None
    language: str | None
    bonuses: list
    player_id: str | None
    vip_status: str | None
    last_deposit: float | None
    last_active: datetime | None
    country: str | None
    timezone: str | None
    attributes: dict
    overrides: dict | None
    attempts_made: int
    next_attempt_at: datetime | None
    is_callback: bool
    #: Latest attempt's duration — populated from ``Call.duration_seconds``,
    #: so the list view doesn't require opening a call's attempts.
    duration_seconds: int | None
    #: Free-text labels (VOAD-28) — see Call.tags's own docstring and
    #: SCallTagsUpdate above for the fixed v1 vocabulary.
    tags: list[str]
    #: SMS sent from this call (VOAD-78): Message rows with status ``sent`` or
    #: ``delivered``. Filled in by the list endpoint with one grouped query;
    #: 0 wherever the count isn't computed.
    sms_sent: int = 0


class SCallDetailsRead(SCallRead):
    attempts: list[SCallAttemptDetailsRead]


class SCallListRead(BaseModel):
    data: list[SCallRead]
    count: int


# ── Readiness ─────────────────────────────────────────────────────────────────
class SReadinessCheck(BaseModel):
    key: str
    ok: bool
    detail: str = ""


class SReadinessRead(BaseModel):
    ready: bool
    checks: list[SReadinessCheck]


# ── Stats (VOAD-38 dashboard) ──────────────────────────────────────────────────
# One global snapshot in one request, backed by a handful of GROUP BY/COUNT
# queries (StatsService) — see repositories/{call,campaign,client,agent}.py's
# "global_*"/"total_count" methods. No per-day/trend data: GET /calls has no
# date-range filter today, so anything beyond a same-request "today" count
# would need one added first.


class SCallOutcomeCount(BaseModel):
    outcome: CallOutcomeEnum
    count: int


class SSentimentCount(BaseModel):
    sentiment: SentimentEnum
    count: int


class SDirectionCount(BaseModel):
    direction: CallDirectionEnum
    count: int


class SCallStatsOverview(BaseModel):
    total: int
    #: Created since local midnight, server-side (UTC) — see StatsService.
    today: int
    #: None when no attempt anywhere has ever connected.
    avg_duration_seconds: float | None
    #: Share of attempts that connected (``answered_at`` set) over every
    #: attempt ever dialed. None when nothing has been dialed yet.
    answer_rate: float | None
    #: Calls with at least one follow-up SMS sent (not failed) — the org's
    #: own definition of "successful", independent of telephony status.
    successful: int
    by_status: list[SCallStatusCount]
    by_outcome: list[SCallOutcomeCount]
    by_sentiment: list[SSentimentCount]
    by_reason_category: list[SReasonCategoryCount]
    by_direction: list[SDirectionCount]


class SCallDailyCount(BaseModel):
    date: date
    total: int
    completed: int
    success: int = 0
    failed: int = 0


class SStatsTimeseries(BaseModel):
    #: Oldest first, one row per day with at least one call in the requested
    #: range — days with zero calls are simply absent.
    days: list[SCallDailyCount]


class SCampaignStatusCount(BaseModel):
    status: CampaignStatusEnum
    count: int


class SCampaignTopByCalls(BaseModel):
    campaign_id: int
    name: str
    calls: int


class SCampaignStatsOverview(BaseModel):
    total: int
    by_status: list[SCampaignStatusCount]
    #: Busiest campaigns first, by total calls ever created for them.
    top_by_calls: list[SCampaignTopByCalls]


class SClientSegmentCount(BaseModel):
    segment: ClientSegmentEnum
    count: int


class SClientStatusCount(BaseModel):
    status: ClientStatusEnum
    count: int


class SClientStatsOverview(BaseModel):
    total: int
    by_segment: list[SClientSegmentCount]
    by_status: list[SClientStatusCount]


class SAgentStatsOverview(BaseModel):
    total: int
    active: int
    inactive: int


class SStatsOverview(BaseModel):
    calls: SCallStatsOverview
    campaigns: SCampaignStatsOverview
    clients: SClientStatsOverview
    agents: SAgentStatsOverview
    #: Total SMS sent org-wide (delivered or pending, i.e. not "failed").
    messages_sent: int


class SActiveGeoCount(BaseModel):
    #: ``Client.country`` verbatim (ISO-3166 code or free text, whichever the
    #: upload provided); None when the client has no country on file.
    country: str | None
    campaigns: int
    calls: int


class SActiveGeoOverview(BaseModel):
    #: GEOs with at least one ``running`` campaign right now, busiest first.
    countries: list[SActiveGeoCount]


# ── Voice Previews ────────────────────────────────────────────────────────────
class SVoicePreviewRequest(BaseModel):
    text: str | None = None
    language: str | None = None
    speed: float | None = None


class SDirectVoicePreviewRequest(BaseModel):
    voice: str
    model_id: int | None = None
    adapter: str | None = None
    text: str | None = None
    language: str | None = None
    speed: float | None = None
