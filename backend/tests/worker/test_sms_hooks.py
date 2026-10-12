"""The SMS delivery-callback surface, full stack: real DB, real redis.

Two things are under test and neither is a vendor's parser — those are covered
against captured payloads in ``tests/engine/test_messaging.py``. Here it is the
router's own contract:

* the locks hold — a forged token, an unknown message, and a Twilio callback
  that is unsigned or unverifiable are all refused;
* a verdict that gets past them is written once and never walked backwards.

The router names no vendor, so each test picks one by writing a messaging row,
which is exactly how production chooses too.
"""

from __future__ import annotations

import httpx
import pytest

import src.main_hooks
from src.application.worker import registry
from src.common.enums.engine import MessageStatusEnum
from src.models.messaging import Message
from src.repositories.messaging import MessageCRUD, MessagingCRUD
from src.settings import SETTINGS
from src.utils.tokens import mint
from src.utils.twilio import signature
from src.utils.url import status_callback_url

#: A public base on the row, so the signed URL is reconstructible without
#: depending on whatever CALL_WORKER__MEDIA_URL happens to be set to.
STATUS_BASE = "https://hooks.invalid"


@pytest.fixture
async def hooks_client():
    transport = httpx.ASGITransport(app=src.main_hooks.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _sent_message(
    session, org_uuid: str, *, adapter: str, provider_ref: str
) -> tuple[int, str]:
    """A route and one message already handed to it. Returns (id, uuid)."""
    route = await MessagingCRUD(session).create(
        {
            "name": f"{adapter}-route",
            "adapter": adapter,
            "is_active": True,
            "auth_token": "token-test",
            "sender": "VIRTA",
            "options": {"status_url_base": STATUS_BASE},
        }
    )
    message = await MessageCRUD(session).create(
        {
            "messaging_id": route.id,
            "to_number": "+359899004167",
            "sender": "VIRTA",
            "body": "тест",
            "segments": 1,
            "status": MessageStatusEnum.sent,
            "provider_ref": provider_ref,
        }
    )
    await session.commit()
    message_id, message_uuid = message.id, str(message.uuid)
    await registry.register_message(message_uuid, org_uuid=org_uuid)
    return message_id, message_uuid


def _url(message_uuid: str) -> str:
    return f"/v1/sms/{message_uuid}/status?t={mint(SETTINGS.secret_key, message_uuid)}"


async def _status_of(session, message_id: int) -> MessageStatusEnum:
    session.expire_all()
    row = await MessageCRUD(session).get_one_or_none(Message.id == message_id)
    return row.status


# ---------------------------------------------------------------------------
# The locks
# ---------------------------------------------------------------------------


async def test_a_forged_token_is_refused_before_any_lookup(hooks_client):
    response = await hooks_client.post("/v1/sms/msg-x/status?t=forged", json=[])
    assert response.status_code == 403


async def test_an_unregistered_message_is_not_found(hooks_client):
    response = await hooks_client.post(_url("msg-x"), json=[])
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# A verdict that gets through
# ---------------------------------------------------------------------------


async def test_a_mamonty_verdict_lands_with_the_vendors_words(
    hooks_client, session, org_uuid
):
    message_id, message_uuid = await _sent_message(
        session, org_uuid, adapter="mamonty", provider_ref="313913312"
    )

    response = await hooks_client.post(
        _url(message_uuid),
        json=[
            {
                "id": 313913312,
                "status": "error",
                "phone": "359899004167",
                "cost": 0.0,
                "error_description": "Routing error",
            }
        ],
    )

    assert response.status_code == 204
    session.expire_all()
    row = await MessageCRUD(session).get_one_or_none(Message.id == message_id)
    assert row.status is MessageStatusEnum.failed
    assert row.error == "Routing error"
    assert row.settled_at is not None


async def test_a_batch_naming_another_message_changes_nothing(
    hooks_client, session, org_uuid
):
    """The provider batches by URL; a verdict on the wrong row is silent damage."""
    message_id, message_uuid = await _sent_message(
        session, org_uuid, adapter="mamonty", provider_ref="313913312"
    )

    response = await hooks_client.post(
        _url(message_uuid), json=[{"id": 999999, "status": "delivered"}]
    )

    assert response.status_code == 204
    assert await _status_of(session, message_id) is MessageStatusEnum.sent


async def test_a_terminal_verdict_is_never_walked_backwards(
    hooks_client, session, org_uuid
):
    message_id, message_uuid = await _sent_message(
        session, org_uuid, adapter="mamonty", provider_ref="1"
    )
    url = _url(message_uuid)

    assert (
        await hooks_client.post(url, json=[{"id": 1, "status": "delivered"}])
    ).status_code == 204
    assert await _status_of(session, message_id) is MessageStatusEnum.delivered

    # Providers retry and reorder; a stale "sent" must lose.
    assert (
        await hooks_client.post(url, json=[{"id": 1, "status": "sent"}])
    ).status_code == 204
    assert await _status_of(session, message_id) is MessageStatusEnum.delivered


async def test_a_provisional_status_is_not_recorded(hooks_client, session, org_uuid):
    message_id, message_uuid = await _sent_message(
        session, org_uuid, adapter="mamonty", provider_ref="1"
    )

    response = await hooks_client.post(
        _url(message_uuid), json=[{"id": 1, "status": "moderation"}]
    )

    assert response.status_code == 204
    assert await _status_of(session, message_id) is MessageStatusEnum.sent


# ---------------------------------------------------------------------------
# Twilio still has to sign — the behaviour the adapter refactor had to preserve
# ---------------------------------------------------------------------------


async def test_an_unsigned_twilio_callback_is_refused(hooks_client, session, org_uuid):
    message_id, message_uuid = await _sent_message(
        session, org_uuid, adapter="twilio", provider_ref="SM-1"
    )

    response = await hooks_client.post(
        _url(message_uuid), data={"MessageStatus": "delivered", "MessageSid": "SM-1"}
    )

    assert response.status_code == 403
    assert await _status_of(session, message_id) is MessageStatusEnum.sent


async def test_a_signed_twilio_callback_is_believed(hooks_client, session, org_uuid):
    message_id, message_uuid = await _sent_message(
        session, org_uuid, adapter="twilio", provider_ref="SM-1"
    )
    form = {"MessageStatus": "delivered", "MessageSid": "SM-1"}
    # Signed over the URL as the sender handed it out, not the one this
    # request arrives on — that is the whole reason both sides share a builder.
    signed = status_callback_url(
        STATUS_BASE, message_uuid, mint(SETTINGS.secret_key, message_uuid)
    )

    response = await hooks_client.post(
        _url(message_uuid),
        data=form,
        headers={"X-Twilio-Signature": signature("token-test", signed, form)},
    )

    assert response.status_code == 204
    assert await _status_of(session, message_id) is MessageStatusEnum.delivered


async def test_a_twilio_signature_over_rewritten_parameters_fails(
    hooks_client, session, org_uuid
):
    """The URL HMAC alone would pass a replay; the signature covers the body."""
    message_id, message_uuid = await _sent_message(
        session, org_uuid, adapter="twilio", provider_ref="SM-1"
    )
    signed = status_callback_url(
        STATUS_BASE, message_uuid, mint(SETTINGS.secret_key, message_uuid)
    )
    captured = signature(
        "token-test", signed, {"MessageStatus": "delivered", "MessageSid": "SM-1"}
    )

    response = await hooks_client.post(
        _url(message_uuid),
        data={"MessageStatus": "failed", "MessageSid": "SM-1"},
        headers={"X-Twilio-Signature": captured},
    )

    assert response.status_code == 403
    assert await _status_of(session, message_id) is MessageStatusEnum.sent
