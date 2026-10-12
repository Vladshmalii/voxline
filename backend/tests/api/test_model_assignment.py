"""Model selection is controlled by platform admins, never client roles."""

import pytest
from sqlalchemy import select

from src.application.services.voice_preview import VoicePreviewService
from src.controller.dependencies.permission import _get_role
from src.models.agent import VoiceAgent
from src.models.provider import Model
from src.repositories.provider import ModelCRUD
from tests.support import seed_stack


@pytest.fixture
def role(app):
    original = app.dependency_overrides[_get_role]

    def set_role(value):
        app.dependency_overrides[_get_role] = lambda: value

    yield set_role
    app.dependency_overrides[_get_role] = original


@pytest.fixture
async def stack(session):
    stack = await seed_stack(session)
    await session.commit()
    return stack


def agent_payload(**extra):
    return dict(
        name="client agent",
        system_prompt="Help",
        spoken_silence="Hello?",
        spoken_reprompt="Again?",
        spoken_goodbye="Bye",
        tts_voice="vivian",
        **extra,
    )


async def assign_defaults(client, stack):
    for kind in ("stt", "tts", "ttt"):
        response = await client.patch(
            f"/v1/models/{getattr(stack, kind).id}", json={"is_default": True}
        )
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("admin_role", ["admin", "super_admin"])
async def test_admin_defaults_and_owner_creation(client, stack, role, admin_role):
    role(admin_role)
    await assign_defaults(client, stack)
    role("owner")
    defaults = (await client.get("/v1/models/defaults")).json()
    response = await client.post("/v1/voice-agents", json=agent_payload())
    assert response.status_code == 201, response.text
    for kind in ("stt", "tts", "ttt"):
        field = f"{kind}_model_id"
        assert response.json()[field] == defaults[field] == getattr(stack, kind).id
    # Normal editing remains possible and preserves the assigned models.
    response = await client.patch(
        f"/v1/voice-agents/{response.json()['id']}", json={"name": "renamed"}
    )
    assert response.status_code == 200
    assert response.json()["tts_model_id"] == stack.tts.id


@pytest.mark.parametrize("field", ["stt_model_id", "tts_model_id", "ttt_model_id"])
@pytest.mark.parametrize("value", [None, 987654])
async def test_owner_cannot_assign_agent_or_language_models(
    client, stack, role, field, value
):
    url = f"/v1/voice-agents/{stack.agent.id}"
    language = await client.post(f"{url}/languages", json={"language": "de"})
    language_id = language.json()["id"]
    role("owner")
    responses = [
        await client.post("/v1/voice-agents", json=agent_payload(**{field: value})),
        await client.patch(url, json={field: value}),
        await client.post(f"{url}/languages", json={"language": "fr", field: value}),
        await client.patch(f"{url}/languages/{language_id}", json={field: value}),
    ]
    assert [response.status_code for response in responses] == [403] * 4
    response = await client.patch(
        f"{url}/languages/{language_id}", json={"voice": "ryan"}
    )
    assert response.status_code == 200


async def test_creation_requires_explicit_defaults(client, stack, role):
    role("owner")
    response = await client.post("/v1/voice-agents", json=agent_payload())
    assert response.status_code == 422
    assert "administrator" in response.json()["detail"]


@pytest.mark.parametrize("client_role", ["owner", "staff", "viewer"])
async def test_clients_cannot_write_models_or_providers(
    client, stack, role, client_role
):
    role(client_role)
    for path, payload in [
        (f"/v1/models/{stack.tts.id}", {"is_default": True}),
        (f"/v1/model-providers/{stack.provider.id}", {"url": "http://other"}),
    ]:
        assert (await client.patch(path, json=payload)).status_code == 403
    assert (
        await client.delete(f"/v1/model-providers/{stack.provider.id}")
    ).status_code == 403


async def test_default_replacement_and_validation(client, stack, session):
    await assign_defaults(client, stack)
    second = await client.post(
        "/v1/models",
        json={
            "name": "other tts",
            "kind": "tts",
            "adapter": "qwen3_tts",
            "code": "other",
            "provider_id": stack.provider.id,
            "is_active": True,
            "is_default": True,
        },
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assert (await client.get(f"/v1/models/{stack.tts.id}")).json()[
        "is_default"
    ] is False
    assert (await client.get("/v1/models/defaults")).json()["tts_model_id"] == second_id
    # Editing other fields must not silently clear the default flag.
    patched = await client.patch(f"/v1/models/{second_id}", json={"name": "renamed"})
    assert patched.json()["is_default"] is True
    rejected = await client.patch(f"/v1/models/{second_id}", json={"is_active": False})
    assert rejected.status_code == 422
    assert (await client.get("/v1/models/defaults")).json()["tts_model_id"] == second_id
    # Defaults affect new agents; existing explicit bindings remain untouched.
    assert (
        await session.execute(
            select(VoiceAgent.tts_model_id).where(VoiceAgent.id == stack.agent.id)
        )
    ).scalar_one() == stack.tts.id


@pytest.mark.parametrize("binding", [None, -100, "wrong_kind", "inactive"])
async def test_admin_binding_validation(client, stack, session, binding):
    if binding == "wrong_kind":
        binding = stack.stt.id
    if binding == "inactive":
        await ModelCRUD(session).update(
            Model.id == stack.tts.id, data={"is_active": False}
        )
        await session.commit()
        binding = stack.tts.id
    response = await client.patch(
        f"/v1/voice-agents/{stack.agent.id}", json={"tts_model_id": binding}
    )
    assert response.status_code == 422


async def test_admin_can_assign_agent_and_language(client, stack):
    response = await client.patch(
        f"/v1/voice-agents/{stack.agent.id}", json={"tts_model_id": stack.tts.id}
    )
    assert response.status_code == 200
    response = await client.post(
        f"/v1/voice-agents/{stack.agent.id}/languages",
        json={"language": "de", "stt_model_id": stack.stt.id},
    )
    assert response.status_code == 201
    response = await client.patch(
        f"/v1/voice-agents/{stack.agent.id}/languages/{response.json()['id']}",
        json={"stt_model_id": None},
    )
    assert response.status_code == 200
    assert response.json()["stt_model_id"] is None


@pytest.mark.parametrize("client_role", ["owner", "staff"])
async def test_preview_uses_default_and_rejects_model_or_adapter(
    client, stack, role, monkeypatch, client_role
):
    await assign_defaults(client, stack)

    async def synthesize(self, config, **kwargs):
        assert config.model.code == stack.tts.code
        return b"audio", "audio/wav"

    monkeypatch.setattr(VoicePreviewService, "synthesize", synthesize)
    role(client_role)
    url = "/v1/voice-agents/preview-voice-direct"
    assert (await client.post(url, json={"voice": "vivian"})).content == b"audio"
    for payload in [
        {"model_id": stack.tts.id},
        {"adapter": "qwen3_tts"},
        {"model_id": None},
    ]:
        assert (
            await client.post(url, json={"voice": "vivian", **payload})
        ).status_code == 403


async def test_owner_cannot_bypass_assignment_via_json(client, stack, role):
    role("owner")
    url = f"/v1/voice-agents/{stack.agent.id}"
    assert (
        await client.patch(url, json={"ttt_extra_body": {"model": "other"}})
    ).status_code == 403
    assert (
        await client.post(
            f"{url}/languages",
            json={"language": "fr", "ttt_params": {"extra_body": {"model": "other"}}},
        )
    ).status_code == 403


@pytest.mark.parametrize("client_role", ["owner", "staff"])
@pytest.mark.parametrize(
    "kind,adapter",
    [("stt", "qwen3_asr"), ("tts", "qwen3_tts"), ("ttt", "openai_compatible")],
)
async def test_call_model_override_is_admin_only(
    client, stack, role, client_role, kind, adapter
):
    role(client_role)
    config = {
        "adapter": adapter,
        "model": {"code": "other", "provider": {"url": "http://other"}},
    }
    if kind == "tts":
        config["voice"] = "vivian"
    response = await client.post(
        "/v1/calls",
        json={
            "agent_id": stack.agent.id,
            "to_number": "+15550000001",
            "overrides": {"language": "en", kind: config},
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("client_role", ["owner", "staff", "viewer"])
@pytest.mark.parametrize("field", ["telephony_id", "messaging_id"])
@pytest.mark.parametrize("value", [None, 987654])
async def test_clients_cannot_assign_or_clear_agent_routes(
    client, stack, role, client_role, field, value
):
    role(client_role)
    response = await client.post(
        "/v1/voice-agents", json=agent_payload(**{field: value})
    )
    assert response.status_code == 403
    response = await client.patch(
        f"/v1/voice-agents/{stack.agent.id}", json={field: value}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("admin_role", ["admin", "super_admin"])
async def test_admin_assigns_routes_and_owner_edits_preserve_them(
    client, stack, role, admin_role
):
    role(admin_role)
    route = await client.post(
        "/v1/messaging",
        json={"name": "SMS", "adapter": "mamonty", "is_active": True},
    )
    assert route.status_code == 201, route.text
    bindings = {"telephony_id": stack.telephony.id, "messaging_id": route.json()["id"]}
    response = await client.post(
        "/v1/voice-agents",
        json=agent_payload(
            **bindings,
            stt_model_id=stack.stt.id,
            tts_model_id=stack.tts.id,
            ttt_model_id=stack.ttt.id,
        ),
    )
    assert response.status_code == 201, response.text
    url = f"/v1/voice-agents/{response.json()['id']}"
    role("owner")
    response = await client.patch(
        url,
        json={
            "name": "Client edit",
            "sms_tool_message": "Hello",
            "sms_tool_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["sms_tool_message"] == "Hello"
    for field, value in bindings.items():
        assert response.json()[field] == value
    role(admin_role)
    response = await client.patch(
        url, json={"telephony_id": None, "messaging_id": None}
    )
    assert response.status_code == 200
    assert response.json()["telephony_id"] is None
    assert response.json()["messaging_id"] is None


async def test_one_analysis_model_per_organization(client, stack):
    url = f"/v1/models/{stack.ttt.id}"
    response = await client.patch(url, json={"is_analysis": True})
    assert response.status_code == 200, response.text
    assert response.json()["is_analysis"] is True
    second = await client.post(
        "/v1/models",
        json={
            "name": "analyst",
            "kind": "ttt",
            "adapter": "openai_compatible",
            "code": "analyst",
            "provider_id": stack.provider.id,
            "is_active": True,
            "is_analysis": True,
        },
    )
    assert second.status_code == 201, second.text
    # Flagging a second model moves the flag rather than failing.
    assert (await client.get(url)).json()["is_analysis"] is False
    # Editing other fields must not silently clear the flag.
    second_url = f"/v1/models/{second.json()['id']}"
    patched = await client.patch(second_url, json={"name": "renamed"})
    assert patched.json()["is_analysis"] is True
    # A flagged model cannot be switched off out from under analysis.
    assert (
        await client.patch(second_url, json={"is_active": False})
    ).status_code == 422
    cleared = await client.patch(second_url, json={"is_analysis": False})
    assert cleared.json()["is_analysis"] is False


@pytest.mark.parametrize("target", ["stt", "tts", "inactive"])
async def test_analysis_model_must_be_active_ttt(client, stack, target):
    if target == "inactive":
        await client.patch(f"/v1/models/{stack.ttt.id}", json={"is_active": False})
        model_id = stack.ttt.id
    else:
        model_id = getattr(stack, target).id
    response = await client.patch(f"/v1/models/{model_id}", json={"is_analysis": True})
    assert response.status_code == 422
    assert "analysis" in response.json()["detail"]


@pytest.mark.parametrize("client_role", ["owner", "staff", "viewer"])
async def test_clients_cannot_pick_analysis_model(client, stack, role, client_role):
    role(client_role)
    response = await client.patch(
        f"/v1/models/{stack.ttt.id}", json={"is_analysis": True}
    )
    assert response.status_code == 403
