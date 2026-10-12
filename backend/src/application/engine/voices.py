"""Which voices a TTS model row can actually speak with.

Same shape as :mod:`readiness`'s probes: a registry of per-adapter coroutines
keyed by :class:`TtsAdapterEnum`, because listing voices is a vendor-API
question, not an engine one — Cartesia and OpenRouter both expose a live
catalogue, Deepgram and Qwen3-TTS do not, and that is a fact about the vendor,
not a branch worth writing into a client. An adapter with no entry here is not
a bug; it is a synthesiser whose voices are a fixed, documented set instead of
a listing endpoint.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import httpx
from cartesia import AsyncCartesia

from src.common.enums.engine import TtsAdapterEnum
from src.integrations.tts.deepgram import voice_language
from src.schemas.engine import ModelConfig
from src.utils.openrouter import api_root as openrouter_root
from src.utils.openrouter import headers as openrouter_headers
from src.utils.url import http_url

#: Per-listing timeout. Same order of magnitude as readiness's probe budget —
#: this is a UI dropdown waiting on it, not a background job.
LIST_TIMEOUT_SECONDS: Final[float] = 10.0

#: Cartesia's REST API, when a provider row leaves the URL empty.
CARTESIA_API_URL: Final[str] = "https://api.cartesia.ai"

#: Hard ceiling on voices pulled from a paginated catalogue, so a runaway
#: account (or a misbehaving mock in a test) cannot turn a dropdown into an
#: unbounded fetch.
MAX_VOICES: Final[int] = 1000


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    """One voice a synthesiser can be asked for, as the row's dropdown wants it."""

    id: str
    name: str
    language: str | None = None


class VoiceListingNotSupported(Exception):
    """Raised when an adapter has no live voice catalogue to list.

    Not an error in the row — Deepgram and Qwen3-TTS voices are a fixed set
    documented on the vendor side, not an endpoint this module could call.
    """

    def __init__(self, adapter: TtsAdapterEnum) -> None:
        self.adapter = adapter
        super().__init__(f"{adapter} has no voice-listing endpoint")


async def _cartesia_voices(model: ModelConfig, timeout: float) -> list[VoiceInfo]:
    base_url = http_url(model.provider.url) if model.provider.url else CARTESIA_API_URL
    client = AsyncCartesia(api_key=model.provider.api_key or "", base_url=base_url)
    try:
        async with asyncio.timeout(timeout):
            voices: list[VoiceInfo] = []
            async for voice in await client.voices.list(limit=100):
                voices.append(
                    VoiceInfo(id=voice.id, name=voice.name, language=voice.language)
                )
                if len(voices) >= MAX_VOICES:
                    break
            return voices
    finally:
        await client.close()


async def _openrouter_voices(model: ModelConfig, timeout: float) -> list[VoiceInfo]:
    # /models is public and lists every slug OpenRouter resells; the row's own
    # code picks which entry's `supported_voices` answers the question. Voice
    # ids carry no separate language field on this API — only the Aura naming
    # convention (`<name>-<lang>`) does, and only some vendors follow it, so a
    # voice this cannot place is listed with language=None rather than guessed.
    root = openrouter_root(http_url(model.provider.url) if model.provider.url else "")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{root}/models",
            params={"output_modalities": "speech"},
            headers=openrouter_headers(model.provider.api_key),
        )
        response.raise_for_status()
        payload = response.json()

    for entry in payload.get("data", []):
        if entry.get("id") != model.code:
            continue
        names = entry.get("supported_voices") or []
        return [
            VoiceInfo(id=name, name=name, language=voice_language(name))
            for name in names[:MAX_VOICES]
        ]
    raise LookupError(f"OpenRouter lists no speech model {model.code!r}")


#: Registry, not a branch — see the module docstring.
VOICE_LISTERS: dict[
    TtsAdapterEnum, Callable[[ModelConfig, float], Awaitable[list[VoiceInfo]]]
] = {
    TtsAdapterEnum.cartesia: _cartesia_voices,
    TtsAdapterEnum.openrouter: _openrouter_voices,
}


async def list_voices(
    model: ModelConfig,
    adapter: TtsAdapterEnum,
    *,
    timeout: float = LIST_TIMEOUT_SECONDS,
) -> list[VoiceInfo]:
    """The voices ``model`` can be asked to speak with.

    Args:
        model: The row's provider and code, as the engine sees it.
        adapter: Which vendor the row binds to.
        timeout: Budget for the vendor call.

    Returns:
        Whatever the vendor's catalogue holds for this model.

    Raises:
        VoiceListingNotSupported: The adapter has no live catalogue.
        LookupError: The adapter has one, but not for this model's code.
    """
    lister = VOICE_LISTERS.get(adapter)
    if lister is None:
        raise VoiceListingNotSupported(adapter)
    return await lister(model, timeout)
