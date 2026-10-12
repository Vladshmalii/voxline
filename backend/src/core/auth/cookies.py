"""Auth cookie names and (un)setting."""

from __future__ import annotations

from fastapi import Response

from src.core.config import Config

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def _common() -> dict:
    cfg = Config.jwt
    return {
        "httponly": True,
        "secure": cfg.cookie_secure,
        "samesite": cfg.cookie_samesite,
        "domain": cfg.cookie_domain,
        "path": "/",
    }


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    cfg = Config.jwt
    refresh_age = cfg.refresh_ttl_days * 86400
    # The access cookie outlives the JWT inside it on purpose: once the JWT
    # expires the browser must still send it, so the API can answer
    # ``token_expired`` (refresh!) instead of a bare ``unauthorized``.
    response.set_cookie(ACCESS_COOKIE, access, max_age=refresh_age, **_common())
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=refresh_age, **_common())


def clear_auth_cookies(response: Response) -> None:
    c = _common()
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(
            name,
            path=c["path"],
            domain=c["domain"],
            secure=c["secure"],
            httponly=True,
            samesite=c["samesite"],
        )
