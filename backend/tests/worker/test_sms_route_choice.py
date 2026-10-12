"""Which SMS route a send goes out on.

One provider is the common case and needs no configuration — the single active
row wins. The moment an organization has two, something has to say which, and
"whichever sorted first" is not an answer: the two rows are different senders,
different prices, often different countries.

So the choice is the agent's, carried on ``VoiceAgent.messaging_id`` and passed
down by the in-call tool. These tests pin the three outcomes that matter: the
default, the explicit pick, and the refusal when neither is available.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from src.application.services.messaging import MessagingService, SendError
from src.common.enums.engine import MessageStatusEnum, MessagingAdapterEnum
from src.integrations.messaging.base import (
    BaseMessagingAdapter,
    MessagingAdapters,
    MessagingCapabilities,
)
from src.repositories.messaging import MessagingCRUD
from src.schemas.admin import SSmsSend


class FakeMessagingAdapter(BaseMessagingAdapter):
    """Records what it was asked to send instead of sending it."""

    # Class-level so a test can inspect it, same as FakeTelephonyAdapter.
    sends: ClassVar[list[dict]] = []

    capabilities = MessagingCapabilities(supports_delivery_status=False)

    @classmethod
    def from_config(cls, config):
        return cls(config)

    def __init__(self, config) -> None:
        self._config = config

    async def send(self, *, to, body, sender=None, status_url=None) -> str:
        # The sender is what tells the routes apart: each row has its own.
        type(self).sends.append({"to": to, "body": body, "sender": self._config.sender})
        return f"ref-{len(type(self).sends)}"


@pytest.fixture
def fake_messaging():
    original = MessagingAdapters.get(MessagingAdapterEnum.mamonty)
    FakeMessagingAdapter.sends = []
    MessagingAdapters[MessagingAdapterEnum.mamonty] = FakeMessagingAdapter
    yield FakeMessagingAdapter
    MessagingAdapters[MessagingAdapterEnum.mamonty] = original


async def _route(session, name: str, *, sender: str, is_active: bool = True):
    return await MessagingCRUD(session).create(
        {
            "name": name,
            "adapter": MessagingAdapterEnum.mamonty,
            "is_active": is_active,
            "auth_token": "key",
            "sender": sender,
        }
    )


async def test_one_active_route_needs_no_choosing(session, org_uuid, fake_messaging):
    await _route(session, "only", sender="ALPHA")
    await session.commit()

    message = await MessagingService(session, org_uuid).send_sms(
        SSmsSend(to="+359899004167", body="hi")
    )

    assert message.status is MessageStatusEnum.sent
    assert fake_messaging.sends[-1]["sender"] == "ALPHA"


async def test_two_active_routes_and_no_pick_is_refused(
    session, org_uuid, fake_messaging
):
    """Silently picking one would text customers from the wrong sender."""
    await _route(session, "one", sender="ALPHA")
    await _route(session, "two", sender="BETA")
    await session.commit()

    with pytest.raises(SendError, match="messaging_id"):
        await MessagingService(session, org_uuid).send_sms(
            SSmsSend(to="+359899004167", body="hi")
        )
    assert fake_messaging.sends == []


async def test_the_named_route_wins_over_the_other_active_one(
    session, org_uuid, fake_messaging
):
    """This is what an agent's ``messaging_id`` buys: a pick, not an error."""
    await _route(session, "one", sender="ALPHA")
    chosen = await _route(session, "two", sender="BETA")
    await session.commit()

    await MessagingService(session, org_uuid).send_sms(
        SSmsSend(to="+359899004167", body="hi", messaging_id=chosen.id)
    )

    assert fake_messaging.sends[-1]["sender"] == "BETA"


async def test_naming_an_inactive_route_is_refused_not_silently_redirected(
    session, org_uuid, fake_messaging
):
    await _route(session, "live", sender="ALPHA")
    retired = await _route(session, "retired", sender="BETA", is_active=False)
    await session.commit()

    with pytest.raises(SendError, match="not active"):
        await MessagingService(session, org_uuid).send_sms(
            SSmsSend(to="+359899004167", body="hi", messaging_id=retired.id)
        )
    assert fake_messaging.sends == []


async def test_naming_a_route_that_does_not_exist_is_refused(
    session, org_uuid, fake_messaging
):
    await _route(session, "live", sender="ALPHA")
    await session.commit()

    with pytest.raises(SendError, match="not found"):
        await MessagingService(session, org_uuid).send_sms(
            SSmsSend(to="+359899004167", body="hi", messaging_id=999999)
        )
    assert fake_messaging.sends == []
