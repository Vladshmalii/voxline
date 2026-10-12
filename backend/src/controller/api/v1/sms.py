"""SMS resource router — sending, and reading what became of what was sent.

Separate from ``/messaging`` (which is CRUD over the *routes*) for the same
reason ``/calls`` is separate from ``/telephony``: one is the binding, the
other is the traffic.

A send is synchronous only up to the provider's acknowledgement. The carrier's
verdict — delivered, undelivered — lands later, by webhook on the hooks
service, so a caller who needs it re-reads the message instead of waiting on
the POST.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from src.application.services.export import MEDIA_TYPES, ExportTooLarge
from src.application.services.messaging import MessagingService, SendError
from src.application.services.sms_history import SmsHistoryService
from src.application.services.sms_stats import SmsStatsService
from src.common.enums.export import ExportFormatEnum
from src.controller.api.responses import export_response
from src.controller.dependencies.db import (
    OrgUuidDep,
    SessionUserCommitDep,
    SessionUserDep,
)
from src.controller.dependencies.permission import view_sms, write_sms
from src.models.messaging import Message
from src.repositories.messaging import MessageCRUD
from src.schemas import admin
from src.schemas.filters import SSmsExportQuery, SSmsListQuery
from src.schemas.sms_stats import SSmsStatsOverview, SSmsStatsTimeseries

router = APIRouter(prefix="/sms", tags=["sms"], dependencies=[view_sms])


def _message_read(message, agent_id, agent_name):
    return admin.SMessageRead.model_validate(message, from_attributes=True).model_copy(
        update={"agent_id": agent_id, "agent_name": agent_name}
    )


@router.post(
    "", response_model=admin.SMessageRead, status_code=201, dependencies=[write_sms]
)
async def send_sms(
    session: SessionUserCommitDep, org_uuid: OrgUuidDep, data: admin.SSmsSend
):
    """Send one SMS through the organization's messaging route.

    Everything refusable is refused before the provider is touched — an
    undialable number, no active route, a route with no sender — and those
    leave no row. A provider rejection *does* leave one, marked ``failed``
    with the vendor's own wording, because "unverified destination" and
    "blocked as spam" need different fixes and both deserve a record.

    The 201 carries the message as of acceptance (``sent``). Re-read it for
    the delivery verdict.
    """
    try:
        message = await MessagingService(session, org_uuid).send_sms(data)
    except SendError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return admin.SMessageRead.model_validate(message, from_attributes=True)


@router.get("", response_model=admin.SMessageListRead)
async def list_sms(session: SessionUserDep, query: Annotated[SSmsListQuery, Query()]):
    messages, count = await SmsHistoryService(session).page(
        query, query.limit, query.offset
    )
    return {
        "data": [
            _message_read(m, agent_id, agent_name)
            for m, agent_id, agent_name in messages
        ],
        "count": count,
    }


@router.get(
    "/export",
    response_class=FileResponse,
    responses={200: {"content": {MEDIA_TYPES[f]: {} for f in ExportFormatEnum}}},
)
async def export_sms(
    session: SessionUserDep, query: Annotated[SSmsExportQuery, Query()]
):
    """Download every message the list shows for the same filters.

    No filters means the whole history. Datetimes are written in ``tz``;
    the filters themselves stay UTC, exactly as on the list.
    """
    try:
        file = await SmsHistoryService(session).export(query, query.format, query.zone)
    except ExportTooLarge as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return export_response(file)


@router.get("/stats/overview", response_model=SSmsStatsOverview)
async def sms_stats_overview(
    session: SessionUserDep,
    messaging_id: int | None = Query(None),
    to: str | None = Query(None),
):
    return await SmsStatsService(session).overview(messaging_id=messaging_id, to=to)


@router.get("/stats/timeseries", response_model=SSmsStatsTimeseries)
async def sms_stats_timeseries(
    session: SessionUserDep,
    date_from: date = Query(...),
    date_to: date = Query(...),
    messaging_id: int | None = Query(None),
    to: str | None = Query(None),
):
    if date_to < date_from:
        raise HTTPException(422, "date_to must not be before date_from")
    if (date_to - date_from) > timedelta(days=89):
        raise HTTPException(422, "range may not exceed 90 days")
    return await SmsStatsService(session).timeseries(
        date_from, date_to, messaging_id=messaging_id, to=to
    )


@router.get("/{item_id}", response_model=admin.SMessageRead)
async def get_sms(session: SessionUserDep, item_id: int):
    rows, _ = await MessageCRUD(session).with_agent(Message.id == item_id, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="message not found")
    return _message_read(*rows[0])
