"""Fixtures for the auth suite: real control database, real cookies, real JWTs.

Needs only Postgres (the permission cache falls back to the database when Redis
is not configured). A scratch control database is created per session and
migrated by the actual control migrations; no tenant database is needed except
in the organization-creation test, which provisions (and drops) one.
"""

from __future__ import annotations

# Bootstrap the environment and Config before importing application modules.
from tests import support  # isort: skip

import httpx
import pytest
from sqlalchemy import text

from src.core.auth.manager import PermissionManager
from src.core.control import service
from src.core.db.session import SessionMaker
from src.settings import SETTINGS

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
def _control_db():
    reason = support.postgres_unavailable()
    if reason:
        pytest.skip(f"auth suite skipped: {reason}")
    support.create_control_database()
    yield
    support.drop_control_database()


@pytest.fixture(scope="session")
def app(_control_db):
    SessionMaker.init(SETTINGS.db)
    import src.main

    return src.main.app


@pytest.fixture(scope="session", autouse=True)
async def _close_engines():
    yield
    await SessionMaker.close()


@pytest.fixture(autouse=True)
async def _clean(request):
    """Empty the control tables between tests that use the database."""
    yield
    if "app" not in request.fixturenames:
        return
    async with SessionMaker.get_control_session()() as session:
        await session.execute(
            text(
                "TRUNCATE refresh_tokens, memberships, organizations, users "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    PermissionManager.clear()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def new_client(app):
    """Factory for extra clients with their own cookie jars (other users)."""
    clients: list[httpx.AsyncClient] = []

    def make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        clients.append(c)
        return c

    yield make
    for c in clients:
        await c.aclose()


class World:
    """Seed helper bound to the control database."""

    async def org(self, name: str = "Acme"):
        async with SessionMaker.get_control_session()() as session:
            org = await service.create_organization(session, name)
            await session.commit()
            return org

    async def user(
        self,
        email: str,
        *,
        superuser: bool = False,
        memberships: dict | None = None,
        active: bool = True,
        password: str = PASSWORD,
    ):
        """``memberships`` maps an Organization to a role string."""
        async with SessionMaker.get_control_session()() as session:
            user = await service.create_user(
                session,
                email=email,
                password=password,
                name=email.split("@")[0],
                is_superuser=superuser,
                is_active=active,
            )
            for org, role in (memberships or {}).items():
                await service.set_membership(session, user.id, org.id, role)
            await session.commit()
            return user


@pytest.fixture
def world(app) -> World:
    return World()


async def login(client: httpx.AsyncClient, email: str, **extra) -> httpx.Response:
    return await client.post(
        "/v1/auth/login", json={"email": email, "password": PASSWORD, **extra}
    )


def expired_access_token(user_id: int, org_uuid: str) -> str:
    import time

    import jwt

    from src.core.config import Config

    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "org": org_uuid,
            "iat": now - 3600,
            "exp": now - 60,
            "typ": "access",
        },
        Config.jwt.secret,
        algorithm=Config.jwt.algorithm,
    )



def replace_cookie(client: httpx.AsyncClient, name: str, value: str) -> None:
    """Overwrite a cookie the server set, keeping its domain/path (no duplicates)."""
    existing = next((c for c in client.cookies.jar if c.name == name), None)
    domain, path = (existing.domain, existing.path) if existing else ("", "/")
    client.cookies.delete(name, domain=domain, path=path)
    client.cookies.set(name, value, domain=domain, path=path)
