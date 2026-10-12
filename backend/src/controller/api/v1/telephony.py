"""Telephony resource router — plain CRUD over carrier/bridge bindings."""

from fastapi import APIRouter, HTTPException, Query

from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import admin_only
from src.models.telephony import Telephony
from src.repositories.telephony import TelephonyCRUD
from src.schemas import admin

router = APIRouter(prefix="/telephony", tags=["telephony"], dependencies=[admin_only])


@router.get("", response_model=list[admin.STelephonyRead])
async def list_telephony(
    session: SessionUserDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items = await TelephonyCRUD(session).get_many_ordered(limit=limit, offset=offset)
    return [admin.STelephonyRead.model_validate(i, from_attributes=True) for i in items]


@router.post("", response_model=admin.STelephonyRead, status_code=201)
async def create_telephony(session: SessionUserCommitDep, data: admin.STelephonyCreate):
    obj = await TelephonyCRUD(session).create(data.model_dump(mode="json"))
    return admin.STelephonyRead.model_validate(obj, from_attributes=True)


@router.get("/{item_id}", response_model=admin.STelephonyRead)
async def get_telephony(session: SessionUserDep, item_id: int):
    obj = await TelephonyCRUD(session).get_one_or_none(Telephony.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="telephony not found")
    return admin.STelephonyRead.model_validate(obj, from_attributes=True)


@router.patch("/{item_id}", response_model=admin.STelephonyRead)
async def update_telephony(
    session: SessionUserCommitDep, item_id: int, data: admin.STelephonyUpdate
):
    payload = data.model_dump(exclude_unset=True, mode="json")
    repo = TelephonyCRUD(session)
    if payload and not await repo.update(Telephony.id == item_id, data=payload):
        raise HTTPException(status_code=404, detail="telephony not found")
    obj = await repo.get_one_or_none(Telephony.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="telephony not found")
    return admin.STelephonyRead.model_validate(obj, from_attributes=True)


@router.delete("/{item_id}", status_code=204)
async def delete_telephony(session: SessionUserCommitDep, item_id: int):
    if not await TelephonyCRUD(session).delete(Telephony.id == item_id):
        raise HTTPException(status_code=404, detail="telephony not found")
