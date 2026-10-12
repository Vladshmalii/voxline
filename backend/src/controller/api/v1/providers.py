"""Model-provider resource router — plain CRUD.

Unlike the payment service, providers are exposed: organizations here bring
their own endpoints and keys per kind, which is the whole point of the
provider-agnostic engine.
"""

from fastapi import APIRouter, HTTPException, Query

from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import providers_access
from src.models.provider import ModelProvider
from src.repositories.provider import ModelProviderCRUD
from src.schemas import admin

router = APIRouter(
    prefix="/model-providers", tags=["model-providers"], dependencies=[providers_access]
)


@router.get("", response_model=list[admin.SModelProviderRead])
async def list_model_providers(
    session: SessionUserDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items = await ModelProviderCRUD(session).get_many_ordered(
        limit=limit, offset=offset
    )
    return [
        admin.SModelProviderRead.model_validate(i, from_attributes=True) for i in items
    ]


@router.post("", response_model=admin.SModelProviderRead, status_code=201)
async def create_model_provider(
    session: SessionUserCommitDep, data: admin.SModelProviderCreate
):
    obj = await ModelProviderCRUD(session).create(data.model_dump(mode="json"))
    return admin.SModelProviderRead.model_validate(obj, from_attributes=True)


@router.get("/{item_id}", response_model=admin.SModelProviderRead)
async def get_model_provider(session: SessionUserDep, item_id: int):
    obj = await ModelProviderCRUD(session).get_one_or_none(ModelProvider.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="model-provider not found")
    return admin.SModelProviderRead.model_validate(obj, from_attributes=True)


@router.patch("/{item_id}", response_model=admin.SModelProviderRead)
async def update_model_provider(
    session: SessionUserCommitDep, item_id: int, data: admin.SModelProviderUpdate
):
    payload = data.model_dump(exclude_unset=True, mode="json")
    # The secret is write-only (never returned), so the edit form sends it
    # blank unless it is being replaced: blank means "keep the stored one".
    if not payload.get("api_key"):
        payload.pop("api_key", None)
    repo = ModelProviderCRUD(session)
    if payload and not await repo.update(ModelProvider.id == item_id, data=payload):
        raise HTTPException(status_code=404, detail="model-provider not found")
    obj = await repo.get_one_or_none(ModelProvider.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="model-provider not found")
    return admin.SModelProviderRead.model_validate(obj, from_attributes=True)


@router.delete("/{item_id}", status_code=204)
async def delete_model_provider(session: SessionUserCommitDep, item_id: int):
    if not await ModelProviderCRUD(session).delete(ModelProvider.id == item_id):
        raise HTTPException(status_code=404, detail="model-provider not found")
