"""Async session factories: one database per organization, plus the control DB."""

from __future__ import annotations

from typing import Any

import orjson
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession as AS
from sqlalchemy.pool import AsyncAdaptedQueuePool

from src.core.config import Config

_CONTROL_KEY = "__control__"


class AsyncSession(AS):
    """AsyncSession that remembers which organization database it is bound to."""

    org_uuid: str

    def __init__(self, *args, **kwargs):
        self.org_uuid = kwargs.pop("org_uuid")
        super().__init__(*args, **kwargs)


class SessionMaker:
    """Engine + sessionmaker cache.

    * ``get_session(org_uuid)`` -> tenant database ``{prefix}{org_uuid}``.
    * ``get_control_session()`` -> the control database (users, organizations,
      memberships, refresh tokens), named by ``settings.control_name``.

    ``init`` takes any object exposing ``url``, ``prefix``, ``control_name`` and
    the pool knobs (``src.settings.DBSettings``). Call ``close`` on shutdown.
    """

    cached_sessions: dict[str, tuple[async_sessionmaker, AsyncEngine]] = {}
    _settings: Any = None

    @classmethod
    def init(cls, settings: Any) -> None:
        cls._settings = settings

    @classmethod
    def _engine_kwargs(cls) -> dict[str, Any]:
        s = cls._settings
        if s is None:
            raise RuntimeError("SessionMaker is not initialized")
        return {
            "pool_size": s.pool_size,
            "max_overflow": s.max_overflow,
            "pool_timeout": s.pool_timeout,
            "pool_recycle": s.pool_recycle,
            "pool_pre_ping": s.pool_pre_ping,
            "poolclass": AsyncAdaptedQueuePool,
            "echo": Config.is_debug,
            "json_deserializer": orjson.loads,
            "json_serializer": lambda o: orjson.dumps(o, default=str).decode(),
        }

    @classmethod
    def get_session(cls, org_uuid: str) -> async_sessionmaker[AsyncSession]:
        """Session maker for an organization's database (created on first use)."""
        cached = cls.cached_sessions.get(org_uuid)
        if cached is not None:
            return cached[0]
        engine = create_async_engine(
            f"{cls._settings.url}/{cls._settings.prefix}{org_uuid}",
            **cls._engine_kwargs(),
        )
        maker = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False, org_uuid=org_uuid
        )
        cls.cached_sessions[org_uuid] = (maker, engine)
        return maker

    @classmethod
    def get_control_session(cls) -> async_sessionmaker[AS]:
        """Session maker for the control database (plain ``AsyncSession``)."""
        cached = cls.cached_sessions.get(_CONTROL_KEY)
        if cached is not None:
            return cached[0]
        engine = create_async_engine(
            f"{cls._settings.url}/{cls._settings.control_name}",
            **cls._engine_kwargs(),
        )
        maker = async_sessionmaker(engine, class_=AS, expire_on_commit=False)
        cls.cached_sessions[_CONTROL_KEY] = (maker, engine)
        return maker

    @classmethod
    async def close(cls) -> None:
        """Dispose every cached engine and clear the cache."""
        sessions = list(cls.cached_sessions.values())
        cls.cached_sessions.clear()
        for _, engine in sessions:
            await engine.dispose()
