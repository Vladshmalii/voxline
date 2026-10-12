"""Twilio wire details shared by the voice leg, the SMS route, and the hooks.

Two things live here because three call sites need them and none of them owns
the other: how a request's API root is derived from region/edge pinning, and
how an inbound webhook's ``X-Twilio-Signature`` is verified.

Signature verification is the only authentication an *inbound* Twilio request
carries. Our own media/status URLs also carry an HMAC of the call uuid, which
is what stops an attacker who has never seen a real URL; the Twilio signature
is what stops one who has — it covers the parameters too, so a replayed URL
with a rewritten ``CallStatus`` fails.

The algorithm, from Twilio's docs: take the full request URL exactly as
Twilio built it, append each POST parameter as ``key + value`` in ascending
key order, HMAC-SHA1 under the account's auth token, base64. A JSON-bodied
webhook instead signs the URL with a ``bodySHA256`` query parameter already
appended — that variant is not implemented here because nothing in this
service asks Twilio for JSON.

Pure functions, no project imports — ``src/utils`` may be used from any layer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping

#: Twilio's public API root; a ``control_url`` overrides it.
TWILIO_API_ROOT = "https://api.twilio.com"


def api_root(
    control_url: str | None = None,
    *,
    region: str | None = None,
    edge: str | None = None,
) -> str:
    """The API root a request should go to.

    Args:
        control_url: Explicit root — a region-pinned deployment, or a
            Twilio-compatible double in tests. Wins over everything.
        region: Twilio region to pin (``ie1``, ``au1``…).
        edge: Twilio edge to pin (``dublin``, ``sydney``…).

    Returns:
        The root, without a trailing slash.
    """
    if control_url:
        return control_url.rstrip("/")
    region_part = f"{region}." if region else ""
    edge_part = f"{edge}." if edge else ""
    if not (region_part or edge_part):
        return TWILIO_API_ROOT
    return f"https://api.{edge_part}{region_part}twilio.com"


def signature(
    auth_token: str, url: str, params: Mapping[str, str] | None = None
) -> str:
    """The signature Twilio would send for this request.

    Args:
        auth_token: The account's auth token — the signing key.
        url: The full URL Twilio was configured with, including query string.
        params: POST form parameters, if any.

    Returns:
        The base64 signature.
    """
    payload = url
    for key in sorted(params or {}):
        payload += f"{key}{params[key]}"
    digest = hmac.new(
        auth_token.encode(), payload.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode()


def verify_signature(
    auth_token: str,
    url: str,
    params: Mapping[str, str] | None,
    presented: str | None,
) -> bool:
    """Constant-time check of a presented ``X-Twilio-Signature``.

    Args:
        auth_token: The account's auth token.
        url: The full URL Twilio was configured with, including query string.
        params: POST form parameters, if any.
        presented: The header value, or None when the header is absent.

    Returns:
        True only for a signature this account could have produced.
    """
    if not (auth_token and presented):
        return False
    return hmac.compare_digest(signature(auth_token, url, params), presented)
