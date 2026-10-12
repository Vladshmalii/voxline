"""STT language listing, against a mocked vendor catalogue — no account needed."""

from __future__ import annotations

import httpx
import pytest

from src.application.engine.config import ModelConfig, ProviderConfig
from src.application.engine.stt_languages import (
    LanguageListingNotSupported,
    list_stt_languages,
)
from src.common.enums.engine import SttAdapterEnum

#: Shaped like Deepgram's ``GET /v1/models``: one entry per model *and*
#: language set, so a model is several entries.
CATALOGUE = {
    "stt": [
        {
            "name": "general-nova-3",
            "canonical_name": "nova-3-general",
            "architecture": "nova-3",
            "languages": ["en", "en-US"],
            "streaming": True,
        },
        {
            "name": "general-nova-3",
            "canonical_name": "nova-3-general",
            "architecture": "nova-3",
            "languages": ["ru", "uk", "multi"],
            "streaming": True,
        },
        {
            "name": "medical-nova-3",
            "canonical_name": "nova-3-medical",
            "architecture": "nova-3",
            "languages": ["en"],
            "streaming": True,
        },
        {
            "name": "general-nova-3",
            "canonical_name": "nova-3-general",
            "architecture": "nova-3",
            "languages": ["xx"],
            "streaming": False,
        },
        {
            "name": "general-nova-2",
            "canonical_name": "nova-2-general",
            "architecture": "nova-2",
            "languages": ["de"],
            "streaming": True,
        },
    ],
    "tts": [],
}


@pytest.fixture
def requests(monkeypatch):
    """Route every ``httpx.AsyncClient`` through a catalogue-serving handler."""
    seen: list[httpx.Request] = []
    original = httpx.AsyncClient.__init__

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=CATALOGUE)

    def patched(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return seen


def model(code: str = "nova-3-general", url: str = "") -> ModelConfig:
    return ModelConfig(code=code, provider=ProviderConfig(url=url, api_key="dg-key"))


async def test_deepgram_unions_the_streaming_entries_of_the_rows_model(requests):
    languages = await list_stt_languages(model(), SttAdapterEnum.deepgram)

    # Both nova-3-general entries, not the medical one, not the batch-only one.
    assert languages == ["en", "en-US", "multi", "ru", "uk"]
    assert str(requests[0].url) == "https://api.deepgram.com/v1/models"
    assert requests[0].headers["Authorization"] == "Token dg-key"


async def test_a_bare_family_code_is_served_by_every_variant(requests):
    languages = await list_stt_languages(model("nova-3"), SttAdapterEnum.deepgram)

    assert languages == ["en", "en-US", "multi", "ru", "uk"]


async def test_the_rows_own_host_is_the_one_asked(requests):
    await list_stt_languages(
        model(url="wss://dg.internal/proxy/"), SttAdapterEnum.deepgram
    )

    assert str(requests[0].url) == "https://dg.internal/proxy/v1/models"


async def test_a_bare_host_row_is_asked_over_https(requests):
    # Deepgram's clients document the base URL as a bare host, and a row saved
    # that way dials calls fine — the listing must not be the thing that 500s.
    await list_stt_languages(model(url="api.deepgram.com"), SttAdapterEnum.deepgram)

    assert str(requests[0].url) == "https://api.deepgram.com/v1/models"


async def test_a_code_the_catalogue_does_not_hold_is_a_lookup_error(requests):
    with pytest.raises(LookupError, match="nova-9"):
        await list_stt_languages(model("nova-9"), SttAdapterEnum.deepgram)


async def test_an_adapter_without_a_catalogue_says_so():
    with pytest.raises(LanguageListingNotSupported):
        await list_stt_languages(model("asr-1"), SttAdapterEnum.qwen3_asr)
