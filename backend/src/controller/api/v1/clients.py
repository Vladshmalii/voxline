"""Client resource router.

Clients are created by upsert wherever a phone number enters the system
(campaign upload, manual originate) — the API only inspects them and edits
what an operator owns: the name, and the callable/do-not-call status.

``list_clients`` doubles as VOAD-34's "lead table" view: every filter the
ticket asks for (status, segment, country, language, vip_status, last_active
range, last_deposit range, phone/name search) is a persistent ``Client``
fact, not something on ``AudienceMember`` (which has no ``status``/``segment``
at all — those only exist on ``Client``), so this endpoint, not
``GET /audiences/{id}/contacts``, is the right home for it.
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)

from src.application.services.client import ClientNotFound, ClientService
from src.application.services.client_import import (
    EXAMPLE_CSV,
    MAX_CSV_BYTES,
    ClientImportService,
)
from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import view_audiences, write_audiences
from src.core.auth.dependencies import get_current_user
from src.core.schemas import SAuthUser
from src.models.client import Client
from src.schemas import admin
from src.schemas.filters import SClientListQuery

router = APIRouter(prefix="/clients", tags=["clients"], dependencies=[view_audiences])


def _client_read(
    client: Client, audiences: list[str], answered_calls: int = 0
) -> admin.SClientRead:
    read = admin.SClientRead.model_validate(client, from_attributes=True)
    read.audiences = audiences
    read.answered_calls = answered_calls
    return read


@router.get("/countries", response_model=list[str])
async def list_client_countries(session: SessionUserDep) -> list[str]:
    """Unique non-empty countries among existing clients."""
    return await ClientService(session).countries()


@router.get("", response_model=admin.SClientListRead)
async def list_clients(
    session: SessionUserDep, query: Annotated[SClientListQuery, Query()]
):
    rows, count = await ClientService(session).page(query, query.limit, query.offset)
    return {"data": [_client_read(*row) for row in rows], "count": count}


@router.get("/{item_id}", response_model=admin.SClientRead)
async def get_client(session: SessionUserDep, item_id: int):
    try:
        client, audiences, answered_calls = await ClientService(session).get(item_id)
    except ClientNotFound:
        raise HTTPException(status_code=404, detail="client not found")
    return _client_read(client, audiences, answered_calls)


@router.patch(
    "/{item_id}", response_model=admin.SClientRead, dependencies=[write_audiences]
)
async def update_client(
    session: SessionUserCommitDep, item_id: int, data: admin.SClientUpdate
):
    try:
        client, audiences = await ClientService(session).update(item_id, data)
    except ClientNotFound:
        raise HTTPException(status_code=404, detail="client not found")
    return _client_read(client, audiences)


@router.get("/import/csv/example")
async def download_import_example() -> Response:
    """Sample CSV in the format :func:`import_clients_csv` accepts."""
    return Response(
        # utf-8-sig: a BOM so Excel opens the Cyrillic name correctly.
        content=EXAMPLE_CSV.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="clients_example.csv"'},
    )


@router.post(
    "/import/csv",
    response_model=admin.SClientImportRead,
    dependencies=[write_audiences],
)
async def import_clients_csv(
    session: SessionUserCommitDep,
    user: Annotated[SAuthUser, Depends(get_current_user)],
    file: UploadFile = File(...),
    audience_name: str | None = Form(
        None,
        description="Optional — files every row that upserts cleanly under "
        "this named Audience (case-insensitive match against an existing "
        "one, else created), so they show up in 'История загрузок' and can "
        "be filtered by audience in the lead table afterward. Leave blank "
        "to only upsert the clients.",
    ),
):
    """Upsert clients by phone from a CSV.

    Optionally also files them under a named audience (``audience_name``) —
    see :meth:`ClientImportService.import_csv`.

    Columns: ``phone`` (required), ``name`` (optional). The header row is
    optional — a bare list of phone numbers uploads as-is. Other columns are
    ignored. A row with a missing or invalid phone is rejected without
    aborting the rest of the file.
    """
    raw = await file.read()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="csv file too large")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="csv file is not valid utf-8")
    results = await ClientImportService(session).import_csv(
        content,
        uploaded_by=user.id,
        filename=file.filename or "",
        audience_name=audience_name,
    )
    accepted = sum(1 for r in results if r.error is None)
    return admin.SClientImportRead(
        accepted=accepted, rejected=len(results) - accepted, results=results
    )
