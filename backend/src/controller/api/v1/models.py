"""Model resource router — plain CRUD, filterable by kind."""

from fastapi import APIRouter, HTTPException, Query

from src.application.services.model import (
    CatalogUnreachable,
    ModelCatalogError,
    ModelNotFound,
    ModelService,
)
from src.common.enums.engine import ProviderKindEnum
from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import admin_only, view_models
from src.models.provider import Model
from src.repositories.provider import ModelCRUD
from src.schemas import admin

router = APIRouter(prefix="/models", tags=["models"], dependencies=[view_models])


@router.get("", response_model=list[admin.SModelRead])
async def list_models(
    session: SessionUserDep,
    kind: ProviderKindEnum | None = Query(None),
    is_active: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items = await ModelService(session).list(
        kind=kind, is_active=is_active, limit=limit, offset=offset
    )
    return [admin.SModelRead.model_validate(i, from_attributes=True) for i in items]


@router.post(
    "", response_model=admin.SModelRead, status_code=201, dependencies=[admin_only]
)
async def create_model(session: SessionUserCommitDep, data: admin.SModelCreate):
    obj = await ModelService(session).create(data)
    return admin.SModelRead.model_validate(obj, from_attributes=True)


@router.get("/defaults", response_model=dict[str, int | None])
async def get_model_defaults(session: SessionUserDep):
    return await ModelService(session).defaults()


@router.get("/{item_id}", response_model=admin.SModelRead)
async def get_model(session: SessionUserDep, item_id: int):
    obj = await ModelCRUD(session).get_one_or_none(Model.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="model not found")
    return admin.SModelRead.model_validate(obj, from_attributes=True)


@router.patch("/{item_id}", response_model=admin.SModelRead, dependencies=[admin_only])
async def update_model(
    session: SessionUserCommitDep, item_id: int, data: admin.SModelUpdate
):
    try:
        obj = await ModelService(session).update(item_id, data)
    except ModelNotFound:
        raise HTTPException(status_code=404, detail="model not found")
    return admin.SModelRead.model_validate(obj, from_attributes=True)


@router.delete("/{item_id}", status_code=204, dependencies=[admin_only])
async def delete_model(session: SessionUserCommitDep, item_id: int):
    if not await ModelCRUD(session).delete(Model.id == item_id):
        raise HTTPException(status_code=404, detail="model not found")


@router.get("/{item_id}/voices", response_model=list[admin.SVoiceRead])
async def list_model_voices(session: SessionUserDep, item_id: int):
    """The voices this TTS model's vendor offers, for a picker to render.

    422 when the adapter has no live catalogue (Deepgram, Qwen3-TTS) — that is
    a fact about the vendor, not a misconfigured row; those voices are a fixed
    set documented on the vendor side instead.
    """
    try:
        voices = await ModelService(session).voices(item_id)
    except ModelNotFound:
        raise HTTPException(status_code=404, detail="model not found")
    except ModelCatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CatalogUnreachable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return [admin.SVoiceRead(id=v.id, name=v.name, language=v.language) for v in voices]


@router.get("/{item_id}/languages", response_model=list[str])
async def list_model_languages(session: SessionUserDep, item_id: int):
    """The language codes this STT model's vendor lists, for a picker to render.

    422 when the adapter has no live catalogue (the self-hosted recognisers,
    Cartesia, OpenRouter) — same contract as ``/voices``: the language field
    stays free text either way, this only feeds its suggestions.
    """
    try:
        return await ModelService(session).languages(item_id)
    except ModelNotFound:
        raise HTTPException(status_code=404, detail="model not found")
    except ModelCatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CatalogUnreachable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
