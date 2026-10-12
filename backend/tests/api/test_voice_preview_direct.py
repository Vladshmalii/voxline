"""``preview-voice-direct`` picks one TTS model when several could speak."""

import pytest

from src.application.services.voice_preview import VoicePreviewService
from src.models.provider import Model
from src.repositories.provider import ModelCRUD
from tests.support import seed_stack

URL = "/v1/voice-agents/preview-voice-direct"
#: Served model codes of the two stacks' TTS rows; both use ``qwen3_tts``.
FIRST, SECOND = "qwen3-tts", "second-tts"


@pytest.fixture
async def stacks(session):
    first = await seed_stack(session)
    second = await seed_stack(session, with_telephony=False)
    await ModelCRUD(session).update(Model.id == second.tts.id, data={"code": SECOND})
    await session.commit()
    return first, second


@pytest.fixture
def spoken(monkeypatch):
    """Served model codes synthesis was asked to speak with, in order."""
    codes = []

    async def synthesize(self, config, **kwargs):
        codes.append(config.model.code)
        return b"audio", "audio/wav"

    monkeypatch.setattr(VoicePreviewService, "synthesize", synthesize)
    return codes


async def preview(client, **payload):
    response = await client.post(URL, json={"voice": "vivian", **payload})
    assert response.status_code == 200, response.text
    assert response.content == b"audio"


@pytest.mark.parametrize("payload", [{}, {"adapter": "qwen3_tts"}])
async def test_prefers_default_then_lowest_id(client, stacks, spoken, payload):
    _, second = stacks
    await preview(client, **payload)
    response = await client.patch(
        f"/v1/models/{second.tts.id}", json={"is_default": True}
    )
    assert response.status_code == 200, response.text
    await preview(client, **payload)
    assert spoken == [FIRST, SECOND]


@pytest.mark.parametrize("payload", [{}, {"adapter": "qwen3_tts"}])
async def test_prefers_active_over_lower_id(client, stacks, session, spoken, payload):
    first, _ = stacks
    await ModelCRUD(session).update(Model.id == first.tts.id, data={"is_active": False})
    await session.commit()
    await preview(client, **payload)
    assert spoken == [SECOND]


async def test_explicit_model_id(client, stacks, spoken):
    first, second = stacks
    await preview(client, model_id=second.tts.id)
    await preview(client, model_id=first.tts.id)
    assert spoken == [SECOND, FIRST]


async def test_unmatched_model_or_adapter(client, stacks, spoken):
    first, _ = stacks
    response = await client.post(URL, json={"voice": "v", "model_id": first.stt.id})
    assert response.status_code == 404
    assert response.json()["detail"] == f"Model id {first.stt.id} not found"
    response = await client.post(URL, json={"voice": "v", "adapter": "cartesia"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith(
        "TTS model for adapter 'cartesia' is not configured in this organization."
    )
    assert spoken == []


async def test_no_tts_model(client, spoken):
    response = await client.post(URL, json={"voice": "vivian"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("No TTS model configured")
