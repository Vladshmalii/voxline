"""Process-wide configuration holder, set once at startup from ``src.settings``."""

from __future__ import annotations

from typing import Any


class Config:
    """Class-level singleton for flags every infrastructure piece needs.

    ``service_prefix`` names the tenant PostgreSQL schema (and namespaces Redis
    keys); ``jwt`` carries the token-signing settings.
    """

    _service_prefix: str | None = None
    is_debug: bool = False
    jwt: Any = None

    @classmethod
    def init(cls, service_prefix: str, is_debug: bool, jwt: Any) -> None:
        """Initialize once; a second call is a bug, not a reconfiguration."""
        if cls._service_prefix is not None:
            raise RuntimeError("Service prefix is already initialized")
        cls._service_prefix = service_prefix
        cls.is_debug = is_debug
        cls.jwt = jwt

    @classmethod
    def get_service_prefix(cls) -> str:
        if cls._service_prefix is None:
            raise RuntimeError("Service prefix is not set")
        return cls._service_prefix
