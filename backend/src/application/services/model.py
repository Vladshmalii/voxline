"""Model rows beyond a plain read: guarded writes and the vendors' catalogues.

Writes go through ``prepare_model_write`` (one default per kind, and a default
must be active; one analysis model per organization, an active TTT one). The catalogues ask the model's vendor live, so their failures
are split by what fixes them: the row or the vendor's offering
(``ModelCatalogError``), or the vendor being unreachable right now
(``CatalogUnreachable``).
"""

from __future__ import annotations

import httpx
from cartesia import CartesiaError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.engine.stt_languages import (
    LanguageListingNotSupported,
    list_stt_languages,
)
from src.application.engine.voices import (
    VoiceInfo,
    VoiceListingNotSupported,
    list_voices,
)
from src.application.services.model_assignment import (
    MODEL_FIELDS,
    prepare_model_write,
)
from src.common.enums.engine import ProviderKindEnum, SttAdapterEnum, TtsAdapterEnum
from src.models.provider import Model
from src.repositories.agent import _model_config
from src.repositories.provider import ModelCRUD
from src.schemas import admin


class ModelNotFound(LookupError):
    """The model id resolves to no row in this organization."""


class ModelCatalogError(ValueError):
    """This model has no catalogue to list; the message says why."""


class CatalogUnreachable(ValueError):
    """The vendor's catalogue could not be reached; the message says why."""


class ModelService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.models = ModelCRUD(session)

    async def _get(self, model_id: int) -> Model:
        model = await self.models.get_one_or_none(Model.id == model_id)
        if model is None:
            raise ModelNotFound(model_id)
        return model

    async def list(
        self,
        *,
        kind: ProviderKindEnum | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Model]:
        clauses = []
        if kind is not None:
            clauses.append(Model.kind == kind)
        if is_active is not None:
            clauses.append(Model.is_active == is_active)
        return await self.models.get_many_ordered(*clauses, limit=limit, offset=offset)

    async def create(self, data: admin.SModelCreate) -> Model:
        payload = data.model_dump(mode="json")
        await prepare_model_write(self.session, payload)
        return await self.models.create(payload)

    async def update(self, model_id: int, data: admin.SModelUpdate) -> Model:
        """Apply the fields ``data`` sets.

        Raises:
            ModelNotFound: If the model does not exist.
        """
        payload = data.model_dump(exclude_unset=True, mode="json")
        await prepare_model_write(self.session, payload, model_id)
        if payload and not await self.models.update(Model.id == model_id, data=payload):
            raise ModelNotFound(model_id)
        return await self._get(model_id)

    async def defaults(self) -> dict[str, int | None]:
        """The default model id per kind (``{"stt_model_id": …}``), None for none."""
        models = await self.models.get_many_ordered(
            Model.is_default.is_(True), Model.is_active.is_(True)
        )
        by_kind = {model.kind: model.id for model in models}
        return {field: by_kind.get(kind) for field, kind in MODEL_FIELDS.items()}

    async def voices(self, model_id: int) -> list[VoiceInfo]:
        """The voices this TTS model's vendor offers.

        Raises:
            ModelNotFound: If the model does not exist.
            ModelCatalogError: Not a TTS model, an unknown adapter, a vendor
                with no voice catalogue, or a lookup the row's config fails.
            CatalogUnreachable: The vendor did not answer.
        """
        model = await self._get(model_id)
        if model.kind != ProviderKindEnum.tts:
            raise ModelCatalogError("voice listing only applies to tts models")
        try:
            adapter = TtsAdapterEnum(model.adapter)
        except ValueError:
            raise ModelCatalogError(f"unknown tts adapter {model.adapter!r}")
        try:
            return await list_voices(_model_config(model), adapter)
        except VoiceListingNotSupported:
            raise ModelCatalogError(f"{adapter.value} has no voice-listing endpoint")
        except LookupError as exc:
            raise ModelCatalogError(str(exc))
        except (httpx.HTTPError, CartesiaError, TimeoutError) as exc:
            raise CatalogUnreachable(f"could not list voices: {exc}")

    async def languages(self, model_id: int) -> list[str]:
        """The language codes this STT model's vendor lists.

        Raises:
            ModelNotFound: If the model does not exist.
            ModelCatalogError: Not an STT model, an unknown adapter, a vendor
                with no language catalogue, or a row its client cannot use.
            CatalogUnreachable: The vendor did not answer.
        """
        model = await self._get(model_id)
        if model.kind != ProviderKindEnum.stt:
            raise ModelCatalogError("language listing only applies to stt models")
        try:
            adapter = SttAdapterEnum(model.adapter)
        except ValueError:
            raise ModelCatalogError(f"unknown stt adapter {model.adapter!r}")
        try:
            return await list_stt_languages(_model_config(model), adapter)
        except LanguageListingNotSupported:
            raise ModelCatalogError(f"{adapter.value} has no language-listing endpoint")
        # A provider URL no client could dial (``ftp://…``) is the row to fix.
        except (LookupError, ValueError) as exc:
            raise ModelCatalogError(str(exc))
        except (httpx.HTTPError, TimeoutError) as exc:
            raise CatalogUnreachable(f"could not list languages: {exc}")
