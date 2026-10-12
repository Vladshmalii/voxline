"""The voice agent and its per-language rows — the tables behind the engine's
three-layer configuration.

:class:`VoiceAgent` accumulates *every* setting a call starts from, per agent,
per organization (the organization boundary is the database itself). It maps
1:1 to :class:`src.application.engine.config.VoiceAgentConfig`;
:class:`AgentLanguage` maps to ``LanguageConfig``. The third layer,
``CallContext``, is per-call data and lives on :class:`src.models.call.Call`.

Two storage shapes, chosen by what the merge does with the value:

* **Columns** for content and bindings an operator edits directly — prompts,
  spoken lines, the voice, model FKs, sampling knobs. Same style as the chat
  service's ``AssistantMixin``.
* **One JSONB column per behavioural section** (``turn``, ``fragment``,
  ``chunking``, ``vad``, ``silence``, ``language_switch``) mirroring the
  engine's section models. The engine merges *whole sections* — a language
  replaces all of ``TurnParams`` or none of it — so a section is one value,
  not a scatter of columns; ``{}`` means "engine defaults", and a section
  gaining a knob is a pydantic default, not a migration across every
  organization database. Rows are validated through the pydantic section
  models at the repository boundary, where an error names the row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.enums.engine import SmsMessageStatusEnum
from src.core.db.models import Base, BaseUUID
from src.core.db.models import Enum as SQL_Enum
from src.models.provider import Model
from src.models.telephony import Telephony

if TYPE_CHECKING:  # see ``VoiceAgent.messaging_id`` for why this is not a plain import
    from src.models.messaging import Messaging


class VoiceAgent(BaseUUID):
    """One organization's agent: the defaults every call starts from.

    Deliberately self-contained — everything ``resolve_profile()`` needs from
    layer 1 is on this row or one FK away, so "why did this call behave that
    way" is answerable by reading this row and at most one language row.
    """

    __uuid_prefix__ = "vagt"

    name: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(server_default="false", default=False)

    # -- languages -----------------------------------------------------------
    default_language: Mapped[str] = mapped_column(default="en", server_default="en")
    #: Speak first. True is what an outbound campaign wants; the engine
    #: additionally gates this on the call actually being outbound.
    greet_first: Mapped[bool] = mapped_column(default=True, server_default="true")
    #: Hang up a call that produced no frames for this long.
    idle_timeout_seconds: Mapped[int] = mapped_column(default=300, server_default="300")
    #: Hard cap on total call length, regardless of activity — distinct from
    #: idle_timeout_seconds above. None means no cap: the only remaining
    #: backstop is the platform-wide CallWorkerSettings.max_call_seconds
    #: sweep, which cleans up a leaked leg's database row but does not itself
    #: end a live call.
    max_duration_seconds: Mapped[int | None] = mapped_column(nullable=True)

    # -- prompts (PromptSet): written natively per language, layer 1 of the
    # prefix cache — anything per-call in here costs the cache fleet-wide.
    # The call script itself lives on Campaign (rendered per call), not here.
    system_prompt: Mapped[str] = mapped_column(Text)
    greeting_kickoff: Mapped[str] = mapped_column(Text, default="", server_default="")

    # -- spoken lines (SpokenPrompts): instant, identical every time, safe to
    # say when the model is unreachable — deliberately not model output.
    spoken_silence: Mapped[str]
    spoken_reprompt: Mapped[str]
    spoken_goodbye: Mapped[str]
    #: Repeated while the caller has picked up but never said a word (before
    #: ``SilencePolicy.reset_timeout_seconds`` gives up) — distinct from
    #: ``spoken_silence``, which handles going quiet mid-conversation. Empty
    #: (the default for an org that hasn't set one) keeps the pre-existing
    #: behaviour: a single silent wait, then hangup with no line spoken.
    spoken_no_answer: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: Feedback-request phrase (VOAD-27), rendered per call via
    #: ``utils.script.render_script(phrase, name=...)`` — a Jinja template,
    #: not literal text, unlike the other spoken_* lines above. Defaults to
    #: empty: an org that hasn't configured one gets no feedback request.
    spoken_feedback_request: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )

    #: Advertises a "send_sms" function to the model. Off by default — see
    #: ``VoiceAgentConfig.sms_tool_enabled``.
    sms_tool_enabled: Mapped[bool] = mapped_column(
        default=False, server_default="false"
    )
    #: The fixed SMS body sent when the agent decides to use the tool
    #: (VOAD-60) — the operator writes this once; the model never composes
    #: its own text and never decides *when* in isolation either, since the
    #: message itself rides in the tool's description for context. Sending
    #: is always deferred to the end of the call, never mid-conversation —
    #: see ``src.application.engine.sms_intent.SmsIntent``.
    sms_tool_message: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: VOAD-62: text written or edited by staff needs owner/admin/
    #: super_admin sign-off before the tool is even offered to the model —
    #: text from owner/admin/super_admin is approved on sight. See
    #: ``src.application.services.agent._apply_sms_moderation``.
    sms_tool_message_status: Mapped[SmsMessageStatusEnum] = mapped_column(
        SQL_Enum(SmsMessageStatusEnum),
        default=SmsMessageStatusEnum.approved,
        server_default=SmsMessageStatusEnum.approved.value,
    )

    # -- behavioural sections, one JSONB per engine section model ------------
    turn: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    fragment: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    chunking: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    vad: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    silence: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )
    language_switch: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )

    # -- model bindings -------------------------------------------------------
    # Required and RESTRICT on purpose: an agent without a recogniser is not a
    # degraded agent, it is a misconfiguration — better to refuse the model's
    # deletion than to let live agents silently lose a pipeline stage.
    stt_model_id: Mapped[int] = mapped_column(ForeignKey(Model.id, ondelete="RESTRICT"))
    tts_model_id: Mapped[int] = mapped_column(ForeignKey(Model.id, ondelete="RESTRICT"))
    ttt_model_id: Mapped[int] = mapped_column(ForeignKey(Model.id, ondelete="RESTRICT"))

    stt_model: Mapped[Model] = relationship(foreign_keys=[stt_model_id], lazy="joined")
    tts_model: Mapped[Model] = relationship(foreign_keys=[tts_model_id], lazy="joined")
    ttt_model: Mapped[Model] = relationship(foreign_keys=[ttt_model_id], lazy="joined")

    # -- per-kind parameters (the scalar halves of Stt/Tts/TttConfig) --------
    #: Language hint sent to recognisers that accept one. None = call language.
    stt_language: Mapped[str | None] = mapped_column(nullable=True)

    tts_voice: Mapped[str]
    tts_sample_rate: Mapped[int] = mapped_column(default=24000, server_default="24000")
    tts_speed: Mapped[float | None] = mapped_column(nullable=True)
    tts_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    ttt_temperature: Mapped[float | None] = mapped_column(nullable=True)
    ttt_top_p: Mapped[float | None] = mapped_column(nullable=True)
    ttt_max_tokens: Mapped[int | None] = mapped_column(nullable=True)
    #: Reasoning models think by default and a phone call cannot wait for it.
    ttt_enable_thinking: Mapped[bool | None] = mapped_column(
        default=False, server_default="false", nullable=True
    )
    #: Escape hatch, merged into the request's ``extra_body``.
    ttt_extra_body: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )

    # -- the leg --------------------------------------------------------------
    #: Which trunk this agent dials through. Nullable so an agent can be
    #: configured before the organization's carrier is — readiness reports it.
    telephony_id: Mapped[int | None] = mapped_column(
        ForeignKey(Telephony.id, ondelete="SET NULL"), nullable=True
    )
    telephony: Mapped[Telephony | None] = relationship(lazy="joined")

    # -- the SMS route --------------------------------------------------------
    #: Which messaging route the in-call ``send_sms`` tool sends through, when
    #: an organization has more than one. Its own binding rather than a reuse
    #: of ``telephony_id``: the trunk that carries audio and the route that
    #: carries text are separate arrangements, and the self-hosted bridge some
    #: agents dial through sends no SMS at all.
    #:
    #: NULL means "the organization's single active route" — which is the
    #: whole configuration for the common case of one provider, and an error
    #: naming this field when there are several. Nullable and SET NULL for the
    #: same reason as the trunk above: an agent may be configured before the
    #: account it will text through exists, and deleting a route must not take
    #: the agent with it. Only consulted when ``sms_tool_enabled`` is on.
    #:
    #: Named by string rather than by class, unlike every other FK on this
    #: model: ``Messaging`` lives in a module that imports ``Call``, which
    #: imports this one, so importing it here would close a cycle. SQLAlchemy
    #: resolves the name against the metadata once every model is loaded,
    #: which is exactly the deferral that breaks it.
    messaging_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{Base.metadata.schema}.messaging.id", ondelete="SET NULL"),
        nullable=True,
    )
    messaging: Mapped[Messaging | None] = relationship("Messaging", lazy="joined")

    languages: Mapped[list[AgentLanguage]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", lazy="selectin"
    )

    def __str__(self):
        return f"{self.name} ({self.default_language})"


class AgentLanguage(Base):
    """What differs for one of the agent's languages — ``LanguageConfig``.

    Every column is nullable: NULL means "use the agent's value". A set
    section replaces the agent's section *whole* — the engine's one-level
    merge, kept honest by the storage shape: there is no way to store half a
    ``TurnParams`` override.
    """

    agent_id: Mapped[int] = mapped_column(ForeignKey(VoiceAgent.id, ondelete="CASCADE"))
    agent: Mapped[VoiceAgent] = relationship(back_populates="languages")

    #: Language code, the way callers send them ("de", "pt-br").
    language: Mapped[str]

    voice: Mapped[str | None] = mapped_column(nullable=True)
    #: PromptSet / SpokenPrompts as whole sections, unlike the agent's columns:
    #: an operator sets a language's prompts together or not at all.
    prompts: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    spoken: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )

    turn: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    fragment: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    chunking: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    vad: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )

    # A language may route to entirely different backends (the recogniser that
    # actually covers it). SET NULL, not RESTRICT: losing an override falls
    # back to the agent's default — degraded but correct — whereas blocking
    # the deletion for a per-language nicety inverts the priority.
    stt_model_id: Mapped[int | None] = mapped_column(
        ForeignKey(Model.id, ondelete="SET NULL"), nullable=True
    )
    tts_model_id: Mapped[int | None] = mapped_column(
        ForeignKey(Model.id, ondelete="SET NULL"), nullable=True
    )
    ttt_model_id: Mapped[int | None] = mapped_column(
        ForeignKey(Model.id, ondelete="SET NULL"), nullable=True
    )
    stt_model: Mapped[Model | None] = relationship(
        foreign_keys=[stt_model_id], lazy="joined"
    )
    tts_model: Mapped[Model | None] = relationship(
        foreign_keys=[tts_model_id], lazy="joined"
    )
    ttt_model: Mapped[Model | None] = relationship(
        foreign_keys=[ttt_model_id], lazy="joined"
    )

    #: Scalar parameters accompanying an overridden kind (a different
    #: recogniser's language hint, a different LLM's sampling), keyed like the
    #: agent's ``stt_language`` / ``tts_*`` / ``ttt_*`` columns but grouped —
    #: they only make sense alongside the section they belong to.
    stt_params: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    tts_params: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )
    ttt_params: Mapped[dict[str, Any] | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )

    __table_args__ = (
        # One row per language per agent — "why did this call use that voice"
        # must resolve to exactly one row.
        UniqueConstraint("agent_id", "language"),
    )

    def __str__(self):
        return f"{self.language} of agent {self.agent_id}"
