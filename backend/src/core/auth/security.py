"""Password hashing, access-token (JWT HS256) and opaque refresh-token helpers."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from loguru import logger

from src.core.config import Config
from src.core.exceptions import (
    TokenExpired,
    TokenInvalid,
    TokenInvalidSignature,
    TokenMalformed,
)
from src.core.schemas import SAuthUser

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def verify_password(password_hash: str, password: str) -> bool:
    """Argon2 is deliberately slow — keep it off the event loop."""
    return await asyncio.to_thread(_verify_password, password_hash, password)


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


# ── access token ─────────────────────────────────────────────────────────────


def create_access_token(user_id: int, organization_uuid: str) -> str:
    cfg = Config.jwt
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": organization_uuid,
        "iat": now,
        "exp": now + cfg.access_ttl_seconds,
        "typ": "access",
    }
    return jwt.encode(payload, cfg.secret, algorithm=cfg.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    cfg = Config.jwt
    try:
        return jwt.decode(token, cfg.secret, algorithms=[cfg.algorithm])
    except jwt.ExpiredSignatureError:
        raise TokenExpired from None
    except jwt.InvalidSignatureError:
        raise TokenInvalidSignature from None
    except jwt.DecodeError:
        raise TokenMalformed from None
    except jwt.InvalidTokenError as e:
        logger.error(f"Auth token invalid: {e}")
        raise TokenInvalid from None


def decode_user_token(token: str) -> SAuthUser:
    payload = decode_token(token)
    if payload.get("typ") != "access":
        raise TokenInvalid
    try:
        return SAuthUser(id=int(payload["sub"]), organization_uuid=payload["org"])
    except (KeyError, ValueError, TypeError):
        raise TokenMalformed from None


# ── refresh token ────────────────────────────────────────────────────────────


def new_refresh_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hex)``; only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
