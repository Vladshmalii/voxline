"""Campaign resource router.

Creation, edits and lifecycle go through ``CampaignService`` (which owns the
template validation and the refusal rules); the dispatcher in the worker does
the dialing. The contacts endpoint is the bulk entry point: it upserts
clients and creates the campaign's calls, returning a per-row verdict.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from src.application.services.campaign import CampaignError, CampaignService
from src.common.enums.campaign import CampaignStatusEnum
from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import view_campaigns, write_campaigns
from src.models.campaign import Campaign
from src.repositories.campaign import CampaignCRUD
from src.schemas import admin

#: One upload is one request and one transaction, with several queries per row.
MAX_UPLOAD_ROWS = 5000

router = APIRouter(
    prefix="/campaigns", tags=["campaigns"], dependencies=[view_campaigns]
)


def _read(campaign: Campaign) -> admin.SCampaignRead:
    return admin.SCampaignRead.model_validate(campaign, from_attributes=True)


@router.get("", response_model=admin.SCampaignListRead)
async def list_campaigns(
    session: SessionUserDep,
    status: list[CampaignStatusEnum] | None = Query(
        None,
        description="Repeatable — e.g. ?status=running&status=paused. A single "
        "value works the same way.",
    ),
    agent_id: int | None = Query(None),
    search: str | None = Query(
        None,
        description="Case-insensitive substring match on name — the "
        "Campaigns tab's free-text search box (VOAD-36).",
    ),
    created_from: datetime | None = Query(
        None, description="Inclusive lower bound on created_at."
    ),
    created_to: datetime | None = Query(
        None, description="Inclusive upper bound on created_at."
    ),
    starts_from: datetime | None = Query(
        None, description="Inclusive lower bound on starts_at."
    ),
    starts_to: datetime | None = Query(
        None, description="Inclusive upper bound on starts_at."
    ),
    include_archived: bool = Query(
        False, description="Also include archived campaigns — hidden by default."
    ),
    sort: str | None = Query(
        None,
        description="One of name|created_at|starts_at|status, optionally "
        "'-'-prefixed for descending (e.g. -created_at). Default: -id "
        "(newest first), unchanged from before VOAD-36.",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        campaigns, count = await CampaignService(session).list(
            status=status,
            agent_id=agent_id,
            search=search,
            created_from=created_from,
            created_to=created_to,
            starts_from=starts_from,
            starts_to=starts_to,
            include_archived=include_archived,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"data": [_read(c) for c in campaigns], "count": count}


@router.post(
    "",
    response_model=admin.SCampaignRead,
    status_code=201,
    dependencies=[write_campaigns],
)
async def create_campaign(session: SessionUserCommitDep, data: admin.SCampaignCreate):
    try:
        campaign = await CampaignService(session).create(data)
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _read(campaign)


@router.get("/{item_id}", response_model=admin.SCampaignRead)
async def get_campaign(session: SessionUserDep, item_id: int):
    obj = await CampaignCRUD(session).get_one_or_none(Campaign.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return _read(obj)


@router.patch(
    "/{item_id}", response_model=admin.SCampaignRead, dependencies=[write_campaigns]
)
async def update_campaign(
    session: SessionUserCommitDep, item_id: int, data: admin.SCampaignUpdate
):
    try:
        campaign = await CampaignService(session).update(item_id, data)
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _read(campaign)


@router.delete("/{item_id}", status_code=204, dependencies=[write_campaigns])
async def delete_campaign(session: SessionUserCommitDep, item_id: int):
    try:
        await CampaignService(session).delete(item_id)
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get(
    "/{item_id}/reason-categories", response_model=admin.SCampaignReasonBreakdown
)
async def campaign_reason_categories(session: SessionUserDep, item_id: int):
    try:
        return await CampaignService(session).reason_breakdown(item_id)
    except CampaignError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{item_id}/counters", response_model=admin.SCampaignCounters)
async def campaign_counters(session: SessionUserDep, item_id: int):
    try:
        return await CampaignService(session).counters(item_id)
    except CampaignError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/{item_id}/contacts",
    response_model=admin.SCampaignUploadRead,
    dependencies=[write_campaigns],
)
async def upload_contacts(
    session: SessionUserCommitDep, item_id: int, rows: list[admin.SCampaignContactRow]
):
    """Upload contacts: upsert clients, strict-validate the script per row,
    create the campaign's calls. Rejected rows return their reason."""
    if len(rows) > MAX_UPLOAD_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"at most {MAX_UPLOAD_ROWS} contacts per upload; split the file",
        )
    try:
        results = await CampaignService(session).upload(item_id, rows)
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    accepted = sum(1 for r in results if r.error is None)
    return admin.SCampaignUploadRead(
        accepted=accepted, rejected=len(results) - accepted, results=results
    )


@router.post(
    "/{item_id}/audiences/{audience_id}",
    response_model=admin.SCampaignUploadRead,
    dependencies=[write_campaigns],
)
async def add_campaign_audience(
    session: SessionUserCommitDep, item_id: int, audience_id: int
):
    """Add every member of an audience to this campaign — same per-row checks
    and duplicate handling as ``POST /contacts``."""
    try:
        results = await CampaignService(session).add_audience(item_id, audience_id)
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    accepted = sum(1 for r in results if r.error is None)
    return admin.SCampaignUploadRead(
        accepted=accepted, rejected=len(results) - accepted, results=results
    )


@router.post(
    "/{item_id}/start",
    response_model=admin.SCampaignRead,
    dependencies=[write_campaigns],
)
async def start_campaign(session: SessionUserCommitDep, item_id: int):
    try:
        return _read(await CampaignService(session).start(item_id))
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/{item_id}/restart",
    response_model=admin.SCampaignRead,
    dependencies=[write_campaigns],
)
async def restart_campaign(session: SessionUserCommitDep, item_id: int):
    try:
        return _read(await CampaignService(session).restart(item_id))
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/{item_id}/pause",
    response_model=admin.SCampaignRead,
    dependencies=[write_campaigns],
)
async def pause_campaign(session: SessionUserCommitDep, item_id: int):
    try:
        return _read(await CampaignService(session).pause(item_id))
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/{item_id}/complete",
    response_model=admin.SCampaignRead,
    dependencies=[write_campaigns],
)
async def complete_campaign(session: SessionUserCommitDep, item_id: int):
    try:
        return _read(await CampaignService(session).complete(item_id))
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{item_id}/error", response_model=admin.SCampaignRead)
async def mark_campaign_error(session: SessionUserCommitDep, item_id: int):
    """Flag a campaign as ``error`` by hand (VOAD-36 interim path — see
    ``CampaignService.mark_error`` for why this isn't automatic yet)."""
    try:
        return _read(await CampaignService(session).mark_error(item_id))
    except CampaignError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
