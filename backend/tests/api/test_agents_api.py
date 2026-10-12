"""The voice-agent resource: section storage semantics, languages, diagnostics."""

from __future__ import annotations

from sqlalchemy import select

from src.models.agent import VoiceAgent
from tests.support import seed_stack


async def _create_agent(client, session, **extra) -> dict:
    stack = await seed_stack(session)
    await session.commit()
    payload = {
        "name": "support",
        "system_prompt": "You are a voice agent.",
        "spoken_silence": "There?",
        "spoken_reprompt": "Go on?",
        "spoken_goodbye": "Bye.",
        "tts_voice": "vivian",
        "stt_model_id": stack.stt.id,
        "tts_model_id": stack.tts.id,
        "ttt_model_id": stack.ttt.id,
        "telephony_id": stack.telephony.id,
        **extra,
    }
    response = await client.post("/v1/voice-agents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_sections_store_sparse_but_read_effective(client, session, org_uuid):
    """An operator who set one knob has set one knob — but reads see it all."""
    body = await _create_agent(client, session, turn={"smart_turn": False})

    # The API answers with the *effective* section: engine defaults filled in.
    assert body["turn"]["smart_turn"] is False
    assert body["turn"]["max_delay_ms"] == 3000  # engine default, not stored

    # The row stores only what was set, so engine defaults keep evolving.
    row_turn = (
        await session.execute(
            select(VoiceAgent.turn).where(VoiceAgent.id == body["id"])
        )
    ).scalar_one()
    assert row_turn == {"smart_turn": False}


async def test_null_section_resets_to_engine_defaults(client, session, org_uuid):
    body = await _create_agent(client, session, turn={"smart_turn": False})

    patched = await client.patch(f"/v1/voice-agents/{body['id']}", json={"turn": None})
    assert patched.status_code == 200
    row_turn = (
        await session.execute(
            select(VoiceAgent.turn).where(VoiceAgent.id == body["id"])
        )
    ).scalar_one()
    assert row_turn == {}
    assert patched.json()["turn"]["smart_turn"] is True  # back to the engine default


async def test_language_rows_nested_crud_and_uniqueness(client, session):
    agent = await _create_agent(client, session)
    url = f"/v1/voice-agents/{agent['id']}/languages"

    created = await client.post(url, json={"language": "de", "voice": "ryan"})
    assert created.status_code == 201

    duplicate = await client.post(url, json={"language": "de"})
    assert duplicate.status_code == 409  # one row per language, by constraint

    details = (await client.get(f"/v1/voice-agents/{agent['id']}")).json()
    assert [l["language"] for l in details["languages"]] == ["de"]

    language_id = created.json()["id"]
    patched = await client.patch(
        f"{url}/{language_id}",
        json={"turn": {"smart_turn": False, "silence_fallback_ms": 1200}},
    )
    assert patched.status_code == 200
    assert patched.json()["turn"]["silence_fallback_ms"] == 1200

    assert (await client.delete(f"{url}/{language_id}")).status_code == 204


async def test_profile_preview_resolves_language_overrides(client, session):
    """The preview runs the real merge — the two-row answer, before any call."""
    agent = await _create_agent(client, session)
    await client.post(
        f"/v1/voice-agents/{agent['id']}/languages",
        json={"language": "de", "voice": "ryan", "turn": {"smart_turn": False}},
    )

    preview = await client.get(
        f"/v1/voice-agents/{agent['id']}/profile", params={"language": "de"}
    )
    assert preview.status_code == 200
    profile = preview.json()
    assert profile["language"] == "de"
    assert profile["tts"]["voice"] == "ryan"
    assert profile["turn"]["smart_turn"] is False

    default = (await client.get(f"/v1/voice-agents/{agent['id']}/profile")).json()
    assert default["tts"]["voice"] == "vivian"


async def test_readiness_offline_checks(client, session):
    # greet_first defaults True but no greeting_kickoff → exactly one check fails.
    agent = await _create_agent(client, session)
    report = (
        await client.get(
            f"/v1/voice-agents/{agent['id']}/readiness", params={"probe": "false"}
        )
    ).json()
    assert report["ready"] is False
    failing = [c["key"] for c in report["checks"] if not c["ok"]]
    assert failing == ["greeting"]

    fixed = await _create_agent(
        client, session, name="second", greeting_kickoff="[open]"
    )
    report = (
        await client.get(
            f"/v1/voice-agents/{fixed['id']}/readiness", params={"probe": "false"}
        )
    ).json()
    assert report["ready"] is True


async def test_the_sms_route_is_pickable_on_the_agent(client, session):
    """Which provider texts the caller is a setting, not a deployment detail.

    Defaults to None — "the organization's single active route" — so an org
    with one provider configures nothing, and one with two says which.
    """
    from src.common.enums.engine import MessagingAdapterEnum
    from src.repositories.messaging import MessagingCRUD

    agent = await _create_agent(client, session)
    assert agent["messaging_id"] is None

    route = await MessagingCRUD(session).create(
        {
            "name": "bulk",
            "adapter": MessagingAdapterEnum.mamonty,
            "is_active": True,
            "auth_token": "key",
            "sender": "VIRTA",
        }
    )
    await session.commit()

    updated = await client.patch(
        f"/v1/voice-agents/{agent['id']}", json={"messaging_id": route.id}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["messaging_id"] == route.id

    reread = await client.get(f"/v1/voice-agents/{agent['id']}")
    assert reread.json()["messaging_id"] == route.id


async def test_agent_404s(client):
    assert (await client.get("/v1/voice-agents/99")).status_code == 404
    assert (await client.get("/v1/voice-agents/99/profile")).status_code == 404
    assert (
        await client.get("/v1/voice-agents/99/readiness?probe=false")
    ).status_code == 404
