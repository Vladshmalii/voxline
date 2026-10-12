"""Fixtures for the worker suite: real DB claims, real queue, fake carrier.

The point of these tests is the conflict story — claim-once, socket-once,
sweep idempotence — so Postgres (org databases and the taskiq queue alike)
and Redis (the handoff registry) are real, same scratch-org pattern as the
API suite. Only the far edge is faked: a telephony adapter that records dials
instead of making them, registered under ``sip_bridge`` in the same registry
the production code resolves.
"""

from __future__ import annotations

# Bootstrap the environment and Config before importing application modules.
from tests import support  # isort: skip

from typing import ClassVar

import pytest

from src.common.enums.engine import TelephonyAdapterEnum
from src.core.db.session import SessionMaker
from src.core.redis import RedisBase
from src.integrations.telephony.base import BaseTelephonyAdapter, TelephonyAdapters
from src.settings import SETTINGS

_reason = support.services_unavailable()
if _reason:
    pytest.skip(f"worker suite skipped: {_reason}", allow_module_level=True)

support.isolate_broker()


@pytest.fixture(scope="session", autouse=True)
async def _queue():
    # sweep_calls kicks re-enqueues itself, which the Postgres broker only
    # allows after startup — in production that's the taskiq CLI's job.
    await support.start_broker()
    yield
    await support.shutdown_broker()


class FakeTelephonyAdapter(BaseTelephonyAdapter):
    """Records dials; optionally fails them. Class-level so tests can inspect."""

    dials: ClassVar[list[dict]] = []
    fail_with: str | None = None

    def __init__(self, config, call_id: str) -> None:
        self._config = config
        self._call_id = call_id

    @classmethod
    def from_config(cls, config, *, call_id: str) -> FakeTelephonyAdapter:
        return cls(config, call_id)

    async def answer_media(self, websocket):
        raise NotImplementedError("media path is not under test here")

    async def dial(self, *, to, media_url, caller_id=None, status_url=None) -> str:
        if type(self).fail_with:
            raise RuntimeError(type(self).fail_with)
        type(self).dials.append(
            {
                "call_id": self._call_id,
                "to": to,
                "media_url": media_url,
                "caller_id": caller_id,
                "status_url": status_url,
            }
        )
        return f"ref-{self._call_id}"


@pytest.fixture(scope="session")
def org_uuid() -> str:
    SessionMaker.init(SETTINGS.db)
    RedisBase.init(SETTINGS.redis)
    org = support.new_org_uuid()
    support.create_org_database(org)
    yield org
    support.drop_org_database(org)


@pytest.fixture
def fake_adapter():
    original = TelephonyAdapters[TelephonyAdapterEnum.sip_bridge]
    FakeTelephonyAdapter.dials = []
    FakeTelephonyAdapter.fail_with = None
    TelephonyAdapters[TelephonyAdapterEnum.sip_bridge] = FakeTelephonyAdapter
    yield FakeTelephonyAdapter
    TelephonyAdapters[TelephonyAdapterEnum.sip_bridge] = original


@pytest.fixture
async def session(org_uuid: str):
    async with SessionMaker.get_session(org_uuid)() as session:
        yield session
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean(org_uuid: str):
    yield
    async with SessionMaker.get_session(org_uuid)() as session:
        from sqlalchemy import text

        await session.execute(
            text(
                'TRUNCATE call.callattempt, call."call", call.campaign, call.client, '
                "call.agentlanguage, call.voiceagent, call.model, call.modelprovider, "
                "call.telephony, call.message, call.messaging "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    await support.purge_queue()
    redis = await RedisBase.get_client()
    # Two namespaces: call handoffs and the message→org map a delivery
    # callback resolves through.
    for pattern in ("call:*", "sms:*"):
        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)
