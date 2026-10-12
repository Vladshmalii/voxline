"""OpenRouter wire details shared by the recogniser, the synthesiser, and the probe.

OpenRouter is one account, one key and one host fronting every speech vendor it
resells, so the three call sites that talk to it need the same two things and
none of them owns the other: where the API root is, and which headers a request
carries.

The headers are worth naming. ``Authorization`` is the only one that is
required; ``HTTP-Referer`` and ``X-OpenRouter-Title`` are attribution, and they
are here rather than hard-coded because the app identity belongs to the
organization's provider row, not to this service — several tenants on one
deployment are several apps as far as OpenRouter's dashboard is concerned.

Pure functions, no project imports — ``src/utils`` may be used from any layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: OpenRouter's public API root; a provider row's URL overrides it.
OPENROUTER_API_ROOT = "https://openrouter.ai/api/v1"

#: Attribution headers, keyed by the ``provider.options`` name that fills them.
#: Both are optional and neither affects routing — they decide how the traffic
#: is labelled on OpenRouter's side.
_APP_HEADERS = {"app_url": "HTTP-Referer", "app_name": "X-OpenRouter-Title"}


def api_root(url: str | None = None) -> str:
    """The API root a request should go to.

    Args:
        url: The provider row's URL — an organization's own gateway, or a
            double in tests. Wins over everything. Empty means the public host.

    Returns:
        The root, without a trailing slash.
    """
    return url.rstrip("/") if url else OPENROUTER_API_ROOT


def headers(
    api_key: str | None, options: Mapping[str, Any] | None = None
) -> dict[str, str]:
    """The headers an OpenRouter request carries.

    Args:
        api_key: The organization's key. Omitted when unset rather than sent
            empty, so the failure is OpenRouter's own "Missing Authentication
            header" instead of a malformed one.
        options: The provider row's ``options``. ``app_url`` and ``app_name``
            become the attribution headers; ``headers`` is merged last and wins,
            for anything this function has not heard of.

    Returns:
        Headers, ready to hand to an HTTP client.
    """
    options = options or {}
    built = {"Content-Type": "application/json"}
    if api_key:
        built["Authorization"] = f"Bearer {api_key}"
    for option, header in _APP_HEADERS.items():
        value = options.get(option)
        if value:
            built[header] = str(value)
    built.update({k: str(v) for k, v in (options.get("headers") or {}).items()})
    return built


def pcm_sample_rate(content_type: str | None) -> int | None:
    """The sample rate an ``audio/pcm`` response declares, if it declares one.

    OpenRouter returns raw PCM with the rate in the content type
    (``audio/pcm;rate=24000;channels=1``) rather than in a container, because
    there is no container. Reading it is not optional: the rate is the upstream
    vendor's, and one account can route ``openai/*`` at 24 kHz and a self-hosted
    model at 16 kHz on consecutive turns. Guessing produces a chipmunk.

    Args:
        content_type: The response's ``Content-Type`` header, or None.

    Returns:
        The declared rate, or None when the header does not carry one.
    """
    if not content_type:
        return None
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "rate":
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None
