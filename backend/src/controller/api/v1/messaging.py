"""Messaging resource router — plain CRUD over an organization's SMS routes.

The same shape as telephony's, and for the same reason: the binding is one
resource, the traffic it carries is another. Sending and message history live
under ``/sms``.

Outbound only throughout. Nothing in this service receives an SMS.
"""

from fastapi import APIRouter, HTTPException, Query

from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import admin_only
from src.models.messaging import Messaging
from src.repositories.messaging import MessagingCRUD
from src.schemas import admin

router = APIRouter(prefix="/messaging", tags=["messaging"], dependencies=[admin_only])


@router.get("", response_model=list[admin.SMessagingRead])
async def list_messaging(
    session: SessionUserDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items = await MessagingCRUD(session).get_many_ordered(limit=limit, offset=offset)
    return [admin.SMessagingRead.model_validate(i, from_attributes=True) for i in items]


@router.post("", response_model=admin.SMessagingRead, status_code=201)
async def create_messaging(session: SessionUserCommitDep, data: admin.SMessagingCreate):
    obj = await MessagingCRUD(session).create(data.model_dump(mode="json"))
    return admin.SMessagingRead.model_validate(obj, from_attributes=True)


@router.get("/{item_id}", response_model=admin.SMessagingRead)
async def get_messaging(session: SessionUserDep, item_id: int):
    obj = await MessagingCRUD(session).get_one_or_none(Messaging.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="messaging not found")
    return admin.SMessagingRead.model_validate(obj, from_attributes=True)


@router.patch("/{item_id}", response_model=admin.SMessagingRead)
async def update_messaging(
    session: SessionUserCommitDep, item_id: int, data: admin.SMessagingUpdate
):
    payload = data.model_dump(exclude_unset=True, mode="json")
    repo = MessagingCRUD(session)
    if payload and not await repo.update(Messaging.id == item_id, data=payload):
        raise HTTPException(status_code=404, detail="messaging not found")
    obj = await repo.get_one_or_none(Messaging.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="messaging not found")
    return admin.SMessagingRead.model_validate(obj, from_attributes=True)


@router.delete("/{item_id}", status_code=204)
async def delete_messaging(session: SessionUserCommitDep, item_id: int):
    if not await MessagingCRUD(session).delete(Messaging.id == item_id):
        raise HTTPException(status_code=404, detail="messaging not found")
