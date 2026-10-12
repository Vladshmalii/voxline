"""Audience resource router — reusable contact lists, added to campaigns via
``POST /campaigns/{id}/audiences/{audience_id}``.

Also home to VOAD-34's upload-batch history (``GET /audiences/uploads``,
backed by ``AudienceUpload``). That route is declared ahead of
``/{item_id}`` below so ``"uploads"`` never gets swallowed by the int-typed
item-id route.

``AudienceUpload`` rows are written by ``AudienceService.add_contacts``/
``add_contacts_csv`` (this module) and by ``ClientImportService.import_csv``
(``src/controller/api/v1/clients.py``, ``audience_id=None`` for that flow).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.application.services.audience import (
    MAX_CSV_BYTES,
    AudienceError,
    AudienceService,
)
from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import view_audiences, write_audiences
from src.core.auth.dependencies import get_current_user
from src.core.schemas import SAuthUser
from src.models.audience import Audience, AudienceMember
from src.repositories.audience import AudienceMemberCRUD
from src.schemas import admin

router = APIRouter(
    prefix="/audiences", tags=["audiences"], dependencies=[view_audiences]
)


def _read(audience: Audience, member_count: int = 0) -> admin.SAudienceRead:
    return admin.SAudienceRead.model_validate(
        audience, from_attributes=True
    ).model_copy(update={"member_count": member_count})


@router.get("/uploads", response_model=admin.SAudienceUploadHistoryListRead)
async def list_audience_uploads(
    session: SessionUserDep,
    audience_id: int | None = Query(
        None, description="Scope to uploads targeting one audience."
    ),
    uploaded_by: int | None = Query(
        None, description="Scope to uploads made by one account user id."
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Upload-batch history (VOAD-34's "История загрузок") — one row per
    CSV/JSON upload event, across both audience-targeted uploads and the
    VOAD-32 status-segment client import (``audience_id`` is null for the
    latter).

    Filtering by ``audience_id`` here, then listing that audience's members
    via ``GET /audiences/{id}/contacts``, is the closest available way to
    see "which leads came from one batch" — see this module's docstring for
    why it isn't exact per-upload-event granularity.
    """
    uploads, count = await AudienceService(session).uploads(
        audience_id=audience_id, uploaded_by=uploaded_by, limit=limit, offset=offset
    )
    data = []
    for upload, audience_name in uploads:
        read = admin.SAudienceUploadHistoryRead.model_validate(
            upload, from_attributes=True
        )
        if upload.audience_id:
            read.audience_name = audience_name
        data.append(read)
    return {
        "data": data,
        "count": count,
    }


@router.get("", response_model=admin.SAudienceListRead)
async def list_audiences(
    session: SessionUserDep,
    include_archived: bool = Query(
        False, description="Also include archived audiences — hidden by default."
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    audiences, count = await AudienceService(session).list(
        include_archived=include_archived, limit=limit, offset=offset
    )
    return {"data": [_read(*row) for row in audiences], "count": count}


@router.post(
    "",
    response_model=admin.SAudienceRead,
    status_code=201,
    dependencies=[write_audiences],
)
async def create_audience(session: SessionUserCommitDep, data: admin.SAudienceCreate):
    audience = await AudienceService(session).create(data)
    return _read(audience)


@router.get("/{item_id}", response_model=admin.SAudienceRead)
async def get_audience(session: SessionUserDep, item_id: int):
    try:
        audience, member_count = await AudienceService(session).get(item_id)
    except AudienceError:
        raise HTTPException(status_code=404, detail="audience not found")
    return _read(audience, member_count)


@router.patch(
    "/{item_id}", response_model=admin.SAudienceRead, dependencies=[write_audiences]
)
async def update_audience(
    session: SessionUserCommitDep, item_id: int, data: admin.SAudienceUpdate
):
    try:
        audience, member_count = await AudienceService(session).update(item_id, data)
    except AudienceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _read(audience, member_count)


@router.delete("/{item_id}", status_code=204, dependencies=[write_audiences])
async def delete_audience(session: SessionUserCommitDep, item_id: int):
    try:
        await AudienceService(session).delete(item_id)
    except AudienceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{item_id}/contacts", response_model=admin.SAudienceMemberListRead)
async def list_audience_contacts(
    session: SessionUserDep,
    item_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    members, count = await AudienceMemberCRUD(session).get_many_with_count(
        AudienceMember.audience_id == item_id,
        order_by=AudienceMember.id.desc(),
        limit=limit,
        offset=offset,
    )
    return {
        "data": [
            admin.SAudienceMemberRead.model_validate(m, from_attributes=True)
            for m in members
        ],
        "count": count,
    }


@router.post(
    "/{item_id}/contacts",
    response_model=admin.SAudienceUploadRead,
    dependencies=[write_audiences],
)
async def upload_audience_contacts(
    session: SessionUserCommitDep,
    item_id: int,
    rows: list[admin.SCampaignContactRow],
    user: Annotated[SAuthUser, Depends(get_current_user)],
):
    """Upsert clients and add them (or refresh their facts) as members."""
    try:
        results = await AudienceService(session).add_contacts(
            item_id, rows, uploaded_by=user.id
        )
    except AudienceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    accepted = sum(1 for r in results if r.error is None)
    return admin.SAudienceUploadRead(
        accepted=accepted, rejected=len(results) - accepted, results=results
    )


@router.post(
    "/{item_id}/contacts/csv",
    response_model=admin.SAudienceUploadRead,
    dependencies=[write_audiences],
)
async def upload_audience_contacts_csv(
    session: SessionUserCommitDep,
    item_id: int,
    user: Annotated[SAuthUser, Depends(get_current_user)],
    file: UploadFile = File(...),
):
    """Same as ``POST /contacts``, from an uploaded CSV file.

    Columns: ``phone`` (required), ``name``, ``language``, ``player_id``,
    ``vip_status``, ``last_deposit``, ``last_active``, ``country``,
    ``timezone``. Any other column becomes a custom attribute.
    """
    raw = await file.read()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="csv file too large")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="csv file is not valid utf-8")
    try:
        results = await AudienceService(session).add_contacts_csv(
            item_id, content, uploaded_by=user.id, filename=file.filename or ""
        )
    except AudienceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    accepted = sum(1 for r in results if r.error is None)
    return admin.SAudienceUploadRead(
        accepted=accepted, rejected=len(results) - accepted, results=results
    )
