"""Token and password primitives: no database needed."""

from __future__ import annotations

from tests import support  # isort: skip

import pytest

from src.core.auth import security
from src.core.exceptions import TokenExpired, TokenInvalidSignature, TokenMalformed
from tests.auth.conftest import expired_access_token


async def test_password_hash_roundtrip():
    hashed = security.hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert await security.verify_password(hashed, "s3cret-pass")
    assert not await security.verify_password(hashed, "other")
    assert not await security.verify_password("not-a-hash", "s3cret-pass")


def test_access_token_roundtrip():
    token = security.create_access_token(7, "org-uuid-1")
    user = security.decode_user_token(token)
    assert (user.id, user.organization_uuid) == (7, "org-uuid-1")


def test_expired_token_raises_token_expired():
    with pytest.raises(TokenExpired) as exc:
        security.decode_user_token(expired_access_token(1, "o"))
    assert exc.value.detail == "token_expired"


def test_garbage_and_tampered_tokens():
    with pytest.raises(TokenMalformed):
        security.decode_user_token("not.a.jwt")
    token = security.create_access_token(1, "o")
    head, payload, sig = token.split(".")
    with pytest.raises(TokenInvalidSignature):
        security.decode_user_token(f"{head}.{payload}.{'A' * len(sig)}")


def test_refresh_tokens_are_random_and_hashed():
    raw1, h1 = security.new_refresh_token()
    raw2, _ = security.new_refresh_token()
    assert raw1 != raw2
    assert h1 == security.hash_refresh_token(raw1) != raw1
    assert len(h1) == 64


def test_support_env_is_loaded():
    assert support.SETTINGS.jwt.secret == "test-jwt-secret-not-for-production"
