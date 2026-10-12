"""Which languages an STT model row can actually be asked to transcribe.

The recogniser-side twin of :mod:`voices`: a registry of per-adapter
coroutines keyed by :class:`SttAdapterEnum`, because "what languages does this
model take" is a vendor-API question, not an engine one. Deepgram publishes a
live model catalogue with a language list per model; the self-hosted
recognisers and the others do not, and an adapter with no entry here is not a
bug — its languages are a fixed, documented set instead of an endpoint.

Whatever a lister returns is a suggestion for a picker, not a whitelist: the
row's language stays free text, so a code the catalogue omits (``multi``, when
an account's listing does not carry it) can still be typed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx

from src.application.engine.readiness import DEEPGRAM_API_URL
from src.common.enums.engine import SttAdapterEnum
from src.integrations.stt.deepgram import DEFAULT_STT_MODEL
from src.schemas.engine import ModelConfig
from src.utils.url import http_url

#: Per-listing timeout — a UI dropdown waits on it, same as the voice list.
LIST_TIMEOUT_SECONDS: Final[float] = 10.0


class LanguageListingNotSupported(Exception):
    """Raised when an adapter has no live catalogue of languages to list."""

    def __init__(self, adapter: SttAdapterEnum) -> None:
        self.adapter = adapter
        super().__init__(f"{adapter} has no language-listing endpoint")


def _deepgram_entries(stt: list[dict[str, Any]], code: str) -> list[dict[str, Any]]:
    """The catalogue entries a row with ``code`` would be served by.

    The catalogue holds one entry per model *and* language set, so a model is
    usually several entries. ``canonical_name`` is what a request's ``model``
    parameter takes, so an exact match there is the answer; failing that, a
    bare family code (``nova-3``) is served by every ``nova-3-*`` variant.
    """
    exact = [e for e in stt if code in (e.get("canonical_name"), e.get("name"))]
    if exact:
        return exact
    return [
        e
        for e in stt
        if e.get("architecture") == code
        or str(e.get("canonical_name", "")).startswith(f"{code}-")
    ]


async def _deepgram_languages(model: ModelConfig, timeout: float) -> list[str]:
    base_url = http_url(model.provider.url) if model.provider.url else DEEPGRAM_API_URL
    headers = (
        {"Authorization": f"Token {model.provider.api_key}"}
        if model.provider.api_key
        else {}
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/v1/models", headers=headers
        )
        response.raise_for_status()
        payload = response.json()

    code = model.code or DEFAULT_STT_MODEL
    # The engine only ever streams, so a batch-only entry is a language this
    # row could not actually use.
    entries = [
        e
        for e in _deepgram_entries(payload.get("stt") or [], code)
        if e.get("streaming", True)
    ]
    if not entries:
        raise LookupError(f"Deepgram lists no streaming stt model {code!r}")
    return sorted({lang for e in entries for lang in e.get("languages") or []})


#: Registry, not a branch — see the module docstring.
STT_LANGUAGE_LISTERS: dict[
    SttAdapterEnum, Callable[[ModelConfig, float], Awaitable[list[str]]]
] = {
    SttAdapterEnum.deepgram: _deepgram_languages,
}


async def list_stt_languages(
    model: ModelConfig,
    adapter: SttAdapterEnum,
    *,
    timeout: float = LIST_TIMEOUT_SECONDS,
) -> list[str]:
    """The language codes ``model`` can be asked to transcribe.

    Args:
        model: The row's provider and code, as the engine sees it.
        adapter: Which vendor the row binds to.
        timeout: Budget for the vendor call.

    Returns:
        The codes the vendor's catalogue holds for this model, sorted.

    Raises:
        LanguageListingNotSupported: The adapter has no live catalogue.
        LookupError: The adapter has one, but not for this model's code.
    """
    lister = STT_LANGUAGE_LISTERS.get(adapter)
    if lister is None:
        raise LanguageListingNotSupported(adapter)
    return await lister(model, timeout)
