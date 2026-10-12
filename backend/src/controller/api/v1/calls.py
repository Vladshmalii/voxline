"""Call resource router.

Calls are *run* by the worker, never by the API — same division as the payment
service's runs. What the API owns: queueing a manual outbound call (with
everything refusable refused up front, via ``CallService``), cancelling one
that is not mid-conversation, and inspection. Campaign calls are created by
the campaign upload, not here.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from src.application.services.call import (
    CallNotCancelable,
    CallNotFound,
    CallService,
    OriginateError,
)
from src.application.services.call_history import (
    CallHistoryService,
    RecordingNotFound,
)
from src.application.services.export import MEDIA_TYPES, ExportTooLarge
from src.common.enums.export import ExportFormatEnum
from src.controller.api.responses import export_response
from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import (
    FullAccessDep,
    view_calls,
    write_calls,
)
from src.models.call import Call
from src.repositories.call import CallCRUD
from src.schemas import admin
from src.schemas.filters import SCallExportQuery, SCallListQuery

router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[view_calls])


def _read_call(call: Call, full_access: bool, details: bool = False) -> admin.SCallRead:
    schema = admin.SCallDetailsRead if details else admin.SCallRead
    read = schema.model_validate(call, from_attributes=True)
    if not full_access:
        read.uuid = None
    return read


@router.get("/stats/summary")
async def call_stats_summary(session: SessionUserDep):
    """Aggregate counts by status and outcome across calls."""
    return await CallHistoryService(session).summary()


@router.get("", response_model=admin.SCallListRead)
async def list_calls(
    session: SessionUserDep,
    full_access: FullAccessDep,
    query: Annotated[SCallListQuery, Query()],
):
    calls, count = await CallHistoryService(session).page(
        query, query.limit, query.offset
    )
    data = []
    for c, sms_sent in calls:
        read = _read_call(c, full_access)
        read.sms_sent = sms_sent
        data.append(read)
    return {"data": data, "count": count}


@router.get(
    "/export",
    response_class=FileResponse,
    responses={200: {"content": {MEDIA_TYPES[f]: {} for f in ExportFormatEnum}}},
)
async def export_calls(
    session: SessionUserDep,
    full_access: FullAccessDep,
    query: Annotated[SCallExportQuery, Query()],
):
    """Download every call the list shows for the same filters.

    No filters means the whole history. One row per call, with the latest
    attempt's timing and summary; transcripts are not included. ``uuid`` is
    masked for the same roles the list masks it for. Datetimes are written in
    ``tz``; the filters themselves stay UTC, exactly as on the list.
    """
    try:
        file = await CallHistoryService(session).export(
            query, query.format, query.zone, full_access
        )
    except ExportTooLarge as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return export_response(file)


@router.post(
    "",
    response_model=admin.SCallDetailsRead,
    status_code=201,
    dependencies=[write_calls],
)
async def originate_call(
    session: SessionUserCommitDep, data: admin.SCallCreate, full_access: FullAccessDep
):
    """Queue a manual outbound call. The worker dials; support reads the rows."""
    if (
        not full_access
        and data.overrides
        and any(
            getattr(data.overrides, kind) is not None for kind in ("stt", "tts", "ttt")
        )
    ):
        raise HTTPException(403, "Only project administrators can override call models")
    try:
        call = await CallService(session).originate(data)
    except OriginateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _read_call(call, full_access, details=True)


@router.get("/{item_id}", response_model=admin.SCallDetailsRead)
async def get_call(session: SessionUserDep, item_id: int, full_access: FullAccessDep):
    obj = await CallCRUD(session).get_one_or_none(Call.id == item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="call not found")
    return _read_call(obj, full_access, details=True)


@router.post(
    "/{item_id}/cancel", response_model=admin.SCallRead, dependencies=[write_calls]
)
async def cancel_call(
    session: SessionUserCommitDep, item_id: int, full_access: FullAccessDep
):
    """Cancel a call that is not mid-conversation; 409 once its leg is dialing."""
    try:
        obj = await CallService(session).cancel(item_id)
    except CallNotFound:
        raise HTTPException(status_code=404, detail="call not found")
    except CallNotCancelable:
        raise HTTPException(status_code=409, detail="call is no longer cancelable")
    return _read_call(obj, full_access)


@router.put(
    "/{item_id}/tags", response_model=admin.SCallRead, dependencies=[write_calls]
)
async def set_call_tags(
    session: SessionUserCommitDep,
    item_id: int,
    data: admin.SCallTagsUpdate,
    full_access: FullAccessDep,
):
    """Replace a call's tags wholesale (VOAD-28).

    Validated up front by ``SCallTagsUpdate`` against the v1 fixed vocabulary
    (plus the "Разговор завершён: <result>" variant); see that schema's
    docstring for why this is call-level, not per-attempt.
    """
    try:
        obj = await CallService(session).set_tags(item_id, data.tags)
    except CallNotFound:
        raise HTTPException(status_code=404, detail="call not found")
    return _read_call(obj, full_access)


@router.get(
    "/{item_id}/attempts/{attempt_id}/recording",
    response_model=admin.SCallAttemptRecordingRead,
)
async def get_call_attempt_recording(
    session: SessionUserDep, item_id: int, attempt_id: int
):
    """Point to one call attempt's recording (VOAD-37).

    This serves whatever ``CallAttempt.recording_url`` already holds — it does
    not itself record anything. As of this change nothing in the call engine
    (``src.application.engine.session.CallSession``) captures audio at all:
    there is no recording processor/observer anywhere in the pipeline, so
    ``recording_url`` is NULL for every attempt today. Wiring real capture
    (e.g. Pipecat's ``AudioBufferProcessor``, uploaded to storage and this
    column set to the resulting URL) touches the live engine/pipeline and is
    out of scope here — see the deployment notes for that follow-up.

    Never a 500 for a legitimately recording-less attempt: a missing call or
    attempt, an attempt that never connected, and an attempt with nothing
    stored yet are each a 404 with a detail message that says which.
    """
    try:
        attempt = await CallHistoryService(session).recording(item_id, attempt_id)
    except RecordingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return admin.SCallAttemptRecordingRead(
        call_id=attempt.call_id,
        attempt_id=attempt.id,
        recording_url=attempt.recording_url,
    )
