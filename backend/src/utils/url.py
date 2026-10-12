"""URL derivations shared across layers. No project imports, per ``utils/`` rules."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

#: How an HTTP scheme reads once the connection is upgraded to a WebSocket.
_WS_SCHEMES = {"http": "ws", "https": "wss"}

#: The same pair read the other way, for the REST side of a vendor's API.
_HTTP_SCHEMES = {value: key for key, value in _WS_SCHEMES.items()}


def websocket_url(base: str, route: str = "") -> str:
    """Derive the WebSocket URI to dial from a provider's base URL.

    A WebSocket handshake is an HTTP request, so ``https://host`` and
    ``wss://host/route`` name the same endpoint — the scheme only selects the
    protocol spoken after the upgrade. A provider row can therefore store one
    HTTP base URL for every kind of client, and the adapters that speak
    WebSocket derive their URI from it here.

    Args:
        base: The provider's URL. ``ws://``/``wss://`` is returned verbatim —
            an operator who pasted the full realtime URL knows their layout
            better than any default. ``http://``/``https://`` has the scheme
            swapped and `route` appended to its path, so a reverse-proxy
            prefix survives: ``https://gw.example.com/vllm`` becomes
            ``wss://gw.example.com/vllm/v1/realtime``.
        route: The path the WebSocket is served on, appended to the base path.

    Returns:
        A ``ws://`` or ``wss://`` URI.

    Raises:
        ValueError: on any other scheme — dialing it would fail anyway, and
            the provider row is the thing to fix.
    """
    parsed = urlsplit(base)
    if parsed.scheme in ("ws", "wss"):
        return base
    scheme = _WS_SCHEMES.get(parsed.scheme)
    if scheme is None:
        raise ValueError(f"{base!r} is not an http(s) or ws(s) URL")
    path = parsed.path.rstrip("/") + route
    return urlunsplit((scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def http_url(base: str) -> str:
    """The HTTP form of a provider URL, for the clients that speak REST.

    The inverse of :func:`websocket_url`, and needed for the same reason: one
    provider row serves every client a vendor offers, and a vendor whose
    realtime endpoint an operator pasted in full (``wss://…``) still has an
    HTTP API behind the same host — its readiness check, its voice list.

    A bare host (``api.deepgram.com``) is taken as ``https://`` — that is the
    form Deepgram's own clients document for a base URL, Pipecat's included,
    so a row a live call dials without complaint must not be the row its
    readiness probe or catalogue listing refuses.

    Args:
        base: The provider's URL, in either scheme family, or a bare host.

    Returns:
        An ``http://`` or ``https://`` URL.

    Raises:
        ValueError: on any other scheme.
    """
    if "://" not in base:
        base = f"https://{base}"
    parsed = urlsplit(base)
    if parsed.scheme in _WS_SCHEMES:
        # Already http(s) — _WS_SCHEMES is keyed by the HTTP schemes.
        return base
    scheme = _HTTP_SCHEMES.get(parsed.scheme)
    if scheme is None:
        raise ValueError(f"{base!r} is not an http(s) or ws(s) URL")
    return urlunsplit(
        (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


def status_callback_url(base: str, message_uuid: str, token: str) -> str:
    """Where a provider should report one message's delivery.

    Built in exactly one place because two call sites must agree character for
    character: the sender hands this string to the provider, and the hooks
    service rebuilds it to check a signature computed over it. A difference as
    small as a trailing slash would make every signed callback fail, and
    behind an ingress neither side can read it off the request.

    Args:
        base: The public base the callback should come back to.
        message_uuid: The message being addressed.
        token: The HMAC of that uuid — see :mod:`src.utils.tokens`.

    Returns:
        The absolute URL.
    """
    return f"{http_url(base.rstrip('/'))}/sms/{message_uuid}/status?t={token}"
