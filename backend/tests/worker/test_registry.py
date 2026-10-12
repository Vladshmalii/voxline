"""The redis handoff: stateless tokens, single-use claims, TTL'd liveness."""

from __future__ import annotations

from src.application.worker import registry

SECRET = "test-secret"


def test_token_verification_is_exact():
    token = registry.media_token(SECRET, "call-1")
    assert registry.verify_token(SECRET, "call-1", token)
    assert not registry.verify_token(SECRET, "call-2", token)  # wrong call
    assert not registry.verify_token("other", "call-1", token)  # wrong secret
    assert not registry.verify_token(SECRET, "call-1", None)
    assert not registry.verify_token(SECRET, "call-1", "")


async def test_claim_is_single_use(org_uuid):
    await registry.register(
        "c1", org_uuid=org_uuid, call_id=7, dial_ttl=30, route_ttl=60
    )

    first = await registry.claim("c1")
    assert first == {"org_uuid": org_uuid, "call_id": 7}
    # Replay, duplicate, scanner — everyone after the first gets nothing.
    assert await registry.claim("c1") is None


async def test_route_outlives_the_claim(org_uuid):
    """Status webhooks arrive long after media connected; routing must not
    be consumed by the media claim."""
    await registry.register(
        "c2", org_uuid=org_uuid, call_id=8, dial_ttl=30, route_ttl=60
    )
    await registry.claim("c2")
    assert await registry.route("c2") == {"org_uuid": org_uuid, "call_id": 8}

    await registry.discard("c2")
    assert await registry.route("c2") is None


async def test_liveness_lock_lifecycle():
    assert not await registry.is_live("c3")
    await registry.mark_live("c3")
    assert await registry.is_live("c3")
    await registry.clear_live("c3")
    assert not await registry.is_live("c3")


async def test_in_flight_counts_pending_and_live(org_uuid):
    assert await registry.in_flight() == 0
    await registry.register(
        "c4", org_uuid=org_uuid, call_id=1, dial_ttl=30, route_ttl=60
    )
    await registry.mark_live("c5")
    # route keys deliberately do not count: they persist for webhook routing
    # long after a call stopped consuming capacity.
    assert await registry.in_flight() == 2
