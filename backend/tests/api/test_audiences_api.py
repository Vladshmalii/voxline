"""Audiences: upload-batch history (VOAD-34's "История загрузок")."""

from __future__ import annotations

import pytest

from src.core.auth.dependencies import get_current_user
from src.core.schemas import SAuthUser


@pytest.fixture
def uploader(app, org_uuid):
    original = app.dependency_overrides[get_current_user]

    def set_uploader(user_id: int):
        app.dependency_overrides[get_current_user] = lambda: SAuthUser(
            id=user_id, organization_uuid=org_uuid
        )

    yield set_uploader
    app.dependency_overrides[get_current_user] = original


async def _import_csv(client, filename: str, audience_name: str | None = None):
    content = "phone,name\n+15551110001,Anna\n,Ben\n"
    response = await client.post(
        "/v1/clients/import/csv",
        files={"file": (filename, content, "text/csv")},
        data={"audience_name": audience_name} if audience_name else {},
    )
    assert response.status_code == 200, response.text
    assert (response.json()["accepted"], response.json()["rejected"]) == (1, 1)


async def _uploads(client, **params) -> dict:
    response = await client.get("/v1/audiences/uploads", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_upload_history_names_each_rows_audience(client, uploader):
    await _import_csv(client, "spring.csv", audience_name="Spring leads")
    await _import_csv(client, "segments.csv")

    created = await client.post("/v1/audiences", json={"name": "VIP"})
    assert created.status_code == 201, created.text
    vip = created.json()
    uploader(2)
    posted = await client.post(
        f"/v1/audiences/{vip['id']}/contacts",
        json=[{"phone": "+15551110003", "name": "Cleo"}, {"phone": "junk"}],
    )
    assert posted.status_code == 200, posted.text

    body = await _uploads(client)
    assert body["count"] == 3
    rows = [
        (
            r["filename"],
            r["audience_name"],
            r["uploaded_by"],
            r["valid_rows"],
            r["invalid_rows"],
        )
        for r in body["data"]
    ]
    # Newest first.
    assert rows == [
        ("", "VIP", 2, 1, 1),
        ("segments.csv", None, 1, 1, 1),
        ("spring.csv", "Spring leads", 1, 1, 1),
    ]
    spring_id = body["data"][2]["audience_id"]
    assert body["data"][0]["audience_id"] == vip["id"]
    assert body["data"][1]["audience_id"] is None
    assert spring_id is not None and spring_id != vip["id"]

    by_audience = await _uploads(client, audience_id=spring_id)
    assert by_audience["count"] == 1
    assert [r["audience_name"] for r in by_audience["data"]] == ["Spring leads"]

    by_uploader = await _uploads(client, uploaded_by=1)
    assert by_uploader["count"] == 2
    assert [r["filename"] for r in by_uploader["data"]] == [
        "segments.csv",
        "spring.csv",
    ]
    by_other = await _uploads(client, uploaded_by=2)
    assert [r["audience_name"] for r in by_other["data"]] == ["VIP"]


async def test_client_import_accepts_bare_phone_list(client):
    """No header, no name column: every number imports (BOM/whitespace tolerated)."""
    content = "\ufeff+15551110011 \r\n+15551110012\r\n"
    response = await client.post(
        "/v1/clients/import/csv",
        files={"file": ("numbers.csv", content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["accepted"], body["rejected"]) == (2, 0)
    assert all(r["error"] is None for r in body["results"])


async def test_client_import_example_is_downloadable_and_importable(client):
    response = await client.get("/v1/clients/import/csv/example")
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    imported = await client.post(
        "/v1/clients/import/csv",
        files={"file": ("clients_example.csv", response.content, "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    assert (imported.json()["accepted"], imported.json()["rejected"]) == (2, 0)
