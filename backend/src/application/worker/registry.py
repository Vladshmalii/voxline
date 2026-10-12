"""Pending-call registry: how a media socket finds its call, exactly once.

The dispatcher that dials (the worker process) and the process that runs the
pipeline (a hooks-service worker, wherever the load balancer lands the
provider's WebSocket) are different processes by design. The handoff state
lives in Redis, keyed by the call's uuid, and the security model is
deliberately simple:

* **Authenticity** is stateless: the media URL carries an HMAC of the call
  uuid under the service secret, so any process can verify a connection
  without a lookup, and nothing an attacker can enumerate produces a valid
  token. This is the primary defense on the internet-facing path (Twilio
  media streams come from IP ranges that aren't committed/filterable).
* **Uniqueness** is one atomic ``GETDEL``: the first socket presenting a
  valid token consumes the pending entry; every later one — replay, scanner,
  duplicate — finds nothing and is refused. Providers do not reconnect a
  media stream mid-call (a dropped socket ends the stream on their side:
  Twilio's ``<Connect><Stream>`` moves on, jambonz's ``listen`` fires its
  close hook), so a second connection for a claimed call is never legitimate.

Three keys per call, all TTL'd so nothing here can leak or drift:

* ``call:pending:{uuid}`` — consumed by the media claim; TTL covers the dial
  window, so an unanswered call's entry evaporates on its own.
* ``call:route:{uuid}`` — org routing for status webhooks, which may arrive
  at any process long after the media claim; TTL covers the maximum call
  lifetime.
* ``call:live:{uuid}`` — the running call's liveness lock, held and refreshed
  by the runner. Its absence for an ``in_progress`` row means the process
  running that call died; the sweep detects the crash within the TTL instead
  of waiting out a max-call-duration timer. The TTLs also make these keys the
  capacity meter: ``pending + live`` *is* the number of calls in flight.
"""

from __future__ import annotations

import json
import time

from src.core.redis import RedisBase
from src.utils import tokens
from src.utils.url import http_url

_PENDING_KEY = "call:pending:{uuid}"
_ROUTE_KEY = "call:route:{uuid}"
_LIVE_KEY = "call:live:{uuid}"
_SMS_ROUTE_KEY = "sms:route:{uuid}"
#: Sorted set of calls in flight: member = call uuid, score = when its slot
#: lapses. One call holds one slot from ``register`` until ``clear_live`` /
#: ``discard``, so counting is ZCARD, not a SCAN over the keyspace.
_SLOTS_KEY = "call:slots"

#: How long a sent message stays resolvable for its delivery callbacks. A
#: carrier may hold an SMS for its validity period (a day or more) before
#: reporting, and Twilio retries a failing callback — so this is generous.
#: After it lapses the callback 404s and the row keeps the status it had,
#: which is the honest outcome, not a wrong one.
SMS_ROUTE_TTL_SECONDS = 7 * 24 * 3600

#: Liveness TTL / refresh cadence for running calls. The TTL is deliberately
#: several refresh periods wide: a missed refresh is a hiccup, three is a body.
LIVE_TTL_SECONDS = 60
LIVE_REFRESH_SECONDS = 20


def media_token(secret: str, call_uuid: str) -> str:
    """The token a media URL for `call_uuid` must carry."""
    return tokens.mint(secret, call_uuid)


def verify_token(secret: str, call_uuid: str, token: str | None) -> bool:
    """Constant-time check of a presented token."""
    return tokens.verify(secret, call_uuid, token)


def call_urls(secret: str, media_base: str, call_uuid: str) -> tuple[str, str]:
    """The media socket URL and the status callback URL for one leg.

    One function because the two must agree: the dialer tells the provider
    these strings, and a provider that signs its webhooks (Twilio signs the
    URL it was handed, character for character) is verified against the same
    derivation. Two call sites building "the same" URL separately is how a
    trailing slash becomes a 403 in production.

    Args:
        secret: The service secret the URL token is minted under.
        media_base: Public base for the hooks service — ``wss://…`` including
            whatever path prefix the ingress adds.
        call_uuid: The attempt's uuid.

    Returns:
        ``(media_url, status_url)``; the status URL is the HTTP form of the
        same origin, since dispositions go where media goes.
    """
    token = media_token(secret, call_uuid)
    base = media_base.rstrip("/")
    return (
        f"{base}/media/{call_uuid}?t={token}",
        f"{http_url(base)}/media/{call_uuid}/status?t={token}",
    )


async def register(
    call_uuid: str, *, org_uuid: str, call_id: int, dial_ttl: int, route_ttl: int
) -> None:
    """Announce a call about to be dialed — before the dial goes out.

    Before, not after: the provider can connect the media socket faster than
    our dial request returns.

    Args:
        call_uuid: The call's uuid (the media URL path segment).
        org_uuid: Organization whose database holds the call row.
        call_id: The call row's id.
        dial_ttl: Seconds the pending entry may wait for its socket.
        route_ttl: Seconds webhook routing stays resolvable.
    """
    payload = json.dumps({"org_uuid": org_uuid, "call_id": call_id})
    client = await RedisBase.get_client()
    await client.set(_PENDING_KEY.format(uuid=call_uuid), payload, ex=dial_ttl)
    await client.set(_ROUTE_KEY.format(uuid=call_uuid), payload, ex=route_ttl)
    await client.zadd(_SLOTS_KEY, {call_uuid: time.time() + dial_ttl})


def media_base(options: dict | None, default: str | None) -> str | None:
    """The public base a carrier connects back to: the telephony row's own
    ``media_url_base`` when set (and non-empty), else the service default.

    One rule for the dialer and for webhook signature checks — they must
    derive the same string or Twilio's signature never verifies.
    """
    return (options or {}).get("media_url_base") or default


async def claim(call_uuid: str) -> dict | None:
    """Consume the pending entry — first caller wins, atomically.

    Returns:
        ``{"org_uuid", "call_id"}`` for the first claimant, None after.
    """
    client = await RedisBase.get_client()
    raw = await client.getdel(_PENDING_KEY.format(uuid=call_uuid))
    return json.loads(raw) if raw else None


async def route(call_uuid: str) -> dict | None:
    """Resolve webhook routing for a call; reading does not consume it."""
    client = await RedisBase.get_client()
    raw = await client.get(_ROUTE_KEY.format(uuid=call_uuid))
    return json.loads(raw) if raw else None


async def register_message(message_uuid: str, *, org_uuid: str) -> None:
    """Make a sent message resolvable to its organization for callbacks.

    The same problem the call route key solves, one layer over: the hooks
    process that receives a delivery callback has no idea which organization's
    database holds the row, and the uuid alone cannot tell it. Written before
    the provider is called, since a fast carrier can report delivery before
    our own send returns.

    Args:
        message_uuid: The message row's uuid.
        org_uuid: Organization whose database holds it.
    """
    client = await RedisBase.get_client()
    await client.set(
        _SMS_ROUTE_KEY.format(uuid=message_uuid), org_uuid, ex=SMS_ROUTE_TTL_SECONDS
    )


async def message_route(message_uuid: str) -> str | None:
    """Which organization holds this message; reading does not consume it."""
    client = await RedisBase.get_client()
    value = await client.get(_SMS_ROUTE_KEY.format(uuid=message_uuid))
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


async def discard(call_uuid: str) -> None:
    """Drop the handoff keys — the dial failed and nothing will ever connect."""
    client = await RedisBase.get_client()
    await client.delete(
        _PENDING_KEY.format(uuid=call_uuid), _ROUTE_KEY.format(uuid=call_uuid)
    )
    await client.zrem(_SLOTS_KEY, call_uuid)


async def mark_live(call_uuid: str) -> None:
    """Assert (or refresh) that this process is running the call right now."""
    client = await RedisBase.get_client()
    await client.set(_LIVE_KEY.format(uuid=call_uuid), "1", ex=LIVE_TTL_SECONDS)
    await client.zadd(_SLOTS_KEY, {call_uuid: time.time() + LIVE_TTL_SECONDS})


async def clear_live(call_uuid: str) -> None:
    """The call ended; release its liveness lock immediately."""
    client = await RedisBase.get_client()
    await client.delete(_LIVE_KEY.format(uuid=call_uuid))
    await client.zrem(_SLOTS_KEY, call_uuid)


async def is_live(call_uuid: str) -> bool:
    """Whether some process currently claims to be running this call."""
    client = await RedisBase.get_client()
    return bool(await client.exists(_LIVE_KEY.format(uuid=call_uuid)))


async def in_flight() -> int:
    """Calls currently dialing or running, platform-wide.

    Lapsed slots (a crashed process stops refreshing its score) are trimmed on
    every read, so a crash cannot leave this number wrong for longer than a
    TTL, and counting costs O(log n), not a keyspace scan.
    """
    client = await RedisBase.get_client()
    await client.zremrangebyscore(_SLOTS_KEY, "-inf", time.time())
    return await client.zcard(_SLOTS_KEY)
