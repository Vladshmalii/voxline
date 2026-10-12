"""Fixtures for the admin API suite: real sessions, real migrations, fake auth.

Everything below the auth line is real — ``SessionMaker`` against a scratch
org database that the actual alembic migration created, real commits, the
taskiq producer pushing to the real local postgres. Only identity is replaced:
``verify_user`` becomes a no-op and ``get_current_user`` returns a user whose
``organization_uuid`` is the scratch org, which is exactly the seam the
multi-tenant session dependency keys on.
"""

from __future__ import annotations

# Bootstrap the environment and Config before importing application modules.
from tests import support  # isort: skip

import httpx
import pytest

from src.controller.dependencies.permission import _get_role, _get_role_ws
from src.core.auth.dependencies import get_current_user, verify_user
from src.core.db.session import SessionMaker
from src.core.enums import SharedRoleEnum
from src.core.redis import RedisBase
from src.core.schemas import SAuthUser
from src.settings import SETTINGS

_reason = support.services_unavailable()
if _reason:
    pytest.skip(f"api suite skipped: {_reason}", allow_module_level=True)

support.isolate_broker()


@pytest.fixture(scope="session", autouse=True)
async def _queue():
    # The producer path (enqueue_dial) starts the broker itself on first kick;
    # the suite only owes the cleanup.
    yield
    await support.shutdown_broker()


@pytest.fixture(scope="session")
def org_uuid() -> str:
    org = support.new_org_uuid()
    support.create_org_database(org)
    yield org
    support.drop_org_database(org)


@pytest.fixture(scope="session")
def app(org_uuid: str):
    SessionMaker.init(SETTINGS.db)
    RedisBase.init(SETTINGS.redis)

    import src.main

    src.main.app.dependency_overrides[verify_user] = lambda: None
    src.main.app.dependency_overrides[get_current_user] = lambda: SAuthUser(
        id=1, organization_uuid=org_uuid
    )
    # Role resolution reads memberships from the control database
    # (``get_permission``); this suite tests endpoint behaviour, not the
    # access matrix, so every request runs as a full-access admin.
    src.main.app.dependency_overrides[_get_role] = lambda: SharedRoleEnum.ADMIN
    src.main.app.dependency_overrides[_get_role_ws] = lambda: SharedRoleEnum.ADMIN
    return src.main.app


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def session(org_uuid: str, app):
    async with SessionMaker.get_session(org_uuid)() as session:
        yield session
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean(org_uuid: str, app):
    """Empty the org schema and the task queue between tests."""
    yield
    async with SessionMaker.get_session(org_uuid)() as session:
        from sqlalchemy import text

        await session.execute(
            text(
                'TRUNCATE call.callattempt, call."call", call.campaign, call.client, '
                "call.agentlanguage, call.voiceagent, call.model, call.modelprovider, "
                "call.telephony, call.message, call.messaging, "
                "call.balancetransaction, call.organizationbalance, "
                "call.audience, call.audienceupload "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    await support.purge_queue()
    redis = await RedisBase.get_client()
    async for key in redis.scan_iter(match="call:*"):
        await redis.delete(key)
