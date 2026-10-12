"""Served models and where they are served — the rows behind ``ModelConfig``.

Same split the chat and payment services use (``ModelProvider`` + ``Model``):
a provider is an endpoint with credentials, a model is one thing served there.
Two organizations pointing at "the same" Voxtral are two providers with two
keys, which is why these rows live in the organization's database and why the
engine builds one client per call from them, never a shared pool.

The mapping to the engine's input contract
(:mod:`src.application.engine.config`):

    ModelProvider  →  ProviderConfig (url, api_key, options)
    Model          →  ModelConfig (code, capabilities) + the adapter the
                      registry resolves (``SttAdapters[adapter]`` etc.)

``adapter`` is a plain string, not a SQL enum, on purpose: the valid values
are the ``*AdapterEnum`` members in :mod:`src.common.enums.engine`, and a new
adapter already ships as a code release — forcing an ``ALTER TYPE`` migration
across every organization database on top of that buys validation nothing the
registry lookup does not already do (an unknown name fails loudly at call
build time, naming the registered adapters).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.enums.engine import ProviderKindEnum
from src.core.db.models import Base
from src.core.db.models import Enum as SQL_Enum


class ModelProvider(Base):
    """One serving endpoint: a vLLM box, a vendor API, a TTS deployment."""

    name: Mapped[str]
    url: Mapped[str]
    api_key: Mapped[str | None] = mapped_column(nullable=True)
    #: Anything the adapter accepts that is not worth a column — proxy
    #: settings, a non-standard path, a vendor flag under test. Mirrors
    #: ``ProviderConfig.options``.
    options: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )

    models: Mapped[list[Model]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class Model(Base):
    """A served model an agent can bind: recogniser, synthesiser, or LLM."""

    name: Mapped[str]
    #: Which side of the pipeline this serves. One table for all three kinds,
    #: because they share every column and the agent binds them by FK anyway.
    kind: Mapped[ProviderKindEnum] = mapped_column(SQL_Enum(ProviderKindEnum))
    #: Registry key — a value of the kind's ``*AdapterEnum``. See the module
    #: docstring for why this is a string column.
    adapter: Mapped[str]
    #: Served model name as the endpoint knows it (``Qwen/Qwen3-ASR-1.7B``).
    code: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default="false", default=False)
    is_default: Mapped[bool] = mapped_column(server_default="false", default=False)
    #: The LLM post-call analysis runs on, for every agent of the organization
    #: (``tasks.analyze_attempt``). At most one row, an active ``ttt`` one;
    #: none set keeps analysis on each call's own LLM.
    is_analysis: Mapped[bool] = mapped_column(server_default="false", default=False)
    #: Overrides for the adapter's declared capabilities — the mechanism that
    #: lets an operator correct a deployment that disagrees with its own
    #: documentation without a release. Mirrors ``ModelConfig.capabilities``.
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey(ModelProvider.id, ondelete="CASCADE")
    )
    provider: Mapped[ModelProvider] = relationship(
        back_populates="models", lazy="joined"
    )

    __table_args__ = (
        # The same served model under the same provider is one row; a second
        # row would be two capability override sets fighting over one truth.
        UniqueConstraint("provider_id", "kind", "code"),
        Index(
            "uq_model_default_kind",
            "kind",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        CheckConstraint("NOT is_default OR is_active", name="ck_model_default_active"),
        Index(
            "uq_model_analysis",
            "is_analysis",
            unique=True,
            postgresql_where=text("is_analysis"),
        ),
        CheckConstraint(
            "NOT is_analysis OR (is_active AND kind = 'ttt')",
            name="ck_model_analysis_active_ttt",
        ),
    )

    def __str__(self):
        return f"{self.kind}:{self.adapter}:{self.code}"
