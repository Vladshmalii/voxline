"""Plain-CRUD resources: providers, models, telephony — through the full stack."""

from __future__ import annotations


async def test_provider_crud_roundtrip(client):
    created = await client.post(
        "/v1/model-providers",
        json={"name": "gpu-1", "url": "http://gpu:8000/v1", "api_key": "k"},
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    got = await client.get(f"/v1/model-providers/{pid}")
    assert got.status_code == 200 and got.json()["name"] == "gpu-1"

    patched = await client.patch(f"/v1/model-providers/{pid}", json={"name": "gpu-2"})
    assert patched.status_code == 200 and patched.json()["name"] == "gpu-2"
    # PATCH is partial: untouched fields survive.
    assert patched.json()["url"] == "http://gpu:8000/v1"

    listed = await client.get("/v1/model-providers")
    assert [p["id"] for p in listed.json()] == [pid]

    assert (await client.delete(f"/v1/model-providers/{pid}")).status_code == 204
    assert (await client.get(f"/v1/model-providers/{pid}")).status_code == 404


async def test_models_filter_by_kind(client):
    pid = (
        await client.post(
            "/v1/model-providers", json={"name": "gpu", "url": "http://gpu:8000/v1"}
        )
    ).json()["id"]
    for kind, adapter, code in (
        ("stt", "qwen3_asr", "asr-1"),
        ("tts", "qwen3_tts", "tts-1"),
    ):
        response = await client.post(
            "/v1/models",
            json={
                "name": code,
                "kind": kind,
                "adapter": adapter,
                "code": code,
                "provider_id": pid,
            },
        )
        assert response.status_code == 201

    stt_only = (await client.get("/v1/models", params={"kind": "stt"})).json()
    assert [m["code"] for m in stt_only] == ["asr-1"]


async def test_telephony_crud_and_options(client):
    created = await client.post(
        "/v1/telephony",
        json={
            "name": "trunk",
            "adapter": "sip_bridge",
            "caller_id": "+15550000001",
            "options": {"media_url_base": "wss://vpc-host/api/v1"},
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["options"]["media_url_base"] == "wss://vpc-host/api/v1"
    assert body["is_active"] is False  # explicit activation is a choice, not a default


async def test_unknown_ids_are_404(client):
    for path in ("/v1/model-providers/99", "/v1/models/99", "/v1/telephony/99"):
        assert (await client.get(path)).status_code == 404


async def test_language_listing_refuses_what_it_cannot_answer(client):
    pid = (
        await client.post(
            "/v1/model-providers", json={"name": "gpu", "url": "http://gpu:8000/v1"}
        )
    ).json()["id"]
    ids = {}
    for kind, adapter, code in (
        ("stt", "qwen3_asr", "asr-1"),
        ("tts", "qwen3_tts", "tts-1"),
    ):
        ids[kind] = (
            await client.post(
                "/v1/models",
                json={
                    "name": code,
                    "kind": kind,
                    "adapter": adapter,
                    "code": code,
                    "provider_id": pid,
                },
            )
        ).json()["id"]

    # A self-hosted recogniser has no catalogue; a synthesiser is the wrong kind.
    no_catalogue = await client.get(f"/v1/models/{ids['stt']}/languages")
    assert no_catalogue.status_code == 422
    assert "no language-listing endpoint" in no_catalogue.json()["detail"]
    assert (await client.get(f"/v1/models/{ids['tts']}/languages")).status_code == 422
    assert (await client.get("/v1/models/99/languages")).status_code == 404
