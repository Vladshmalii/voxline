"""Messaging adapters: registry, capability overrides, segments, the vendor wires.

No network: every adapter here posts through ``httpx``, so its request is
exercised against a transport double and judged by what it would have put on
the wire.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.common.enums.engine import MessageStatusEnum, MessagingAdapterEnum
from src.integrations.messaging import (
    MamontyMessagingAdapter,
    MessagingConfig,
    TwilioMessagingAdapter,
    build_messaging,
)
from src.integrations.messaging.mamonty import MAMONTY_API_ROOT
from src.utils.twilio import TWILIO_API_ROOT, api_root, signature, verify_signature


def config(**overrides) -> MessagingConfig:
    defaults = {
        "adapter": MessagingAdapterEnum.twilio,
        "account_id": "AC-test",
        "auth_token": "token-test",
        "sender": "+15550000000",
    }
    defaults.update(overrides)
    return MessagingConfig(**defaults)


class Recorder:
    """Captures the one request an adapter makes and answers it."""

    def __init__(self, status: int = 201, payload: dict | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._status = status
        self._payload = payload if payload is not None else {"sid": "SM-1"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status, json=self._payload)

    @property
    def form(self) -> dict[str, str]:
        from urllib.parse import parse_qsl

        return dict(parse_qsl(self.requests[-1].content.decode()))

    @property
    def json(self) -> dict:
        """The last request's body, for the adapters that post JSON."""
        return json.loads(self.requests[-1].content.decode())


def _install(monkeypatch, recorder: Recorder) -> Recorder:
    """Route every ``httpx.AsyncClient`` in this test through `recorder`."""
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(recorder.handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return recorder


@pytest.fixture
def recorder(monkeypatch):
    return _install(monkeypatch, Recorder())


@pytest.fixture
def recording(monkeypatch):
    """A recorder with a chosen response, for tests that need a specific body."""

    def install(status: int = 200, payload: dict | None = None) -> Recorder:
        return _install(monkeypatch, Recorder(status=status, payload=payload))

    return install


# ---------------------------------------------------------------------------
# Registry and capability overrides
# ---------------------------------------------------------------------------


def test_the_registry_resolves_the_adapter():
    assert isinstance(build_messaging(config()), TwilioMessagingAdapter)


def test_an_unregistered_adapter_names_what_is_registered(monkeypatch):
    from src.integrations.messaging import base

    monkeypatch.setattr(base, "MessagingAdapters", {})
    with pytest.raises(KeyError, match="Registered"):
        base.build_messaging(config())


def test_capability_overrides_come_from_the_row():
    """A route whose destinations refuse sender ids is a DB row, not a release."""
    adapter = build_messaging(
        config(capabilities={"supports_alphanumeric_sender": False})
    )
    assert adapter.capabilities.supports_alphanumeric_sender is False
    # Untouched fields keep the adapter's defaults.
    assert adapter.capabilities.segment_chars == 160


def test_unknown_capability_overrides_are_ignored_not_fatal():
    adapter = build_messaging(config(capabilities={"tyop": True}))
    assert adapter.capabilities.segment_chars == 160


# ---------------------------------------------------------------------------
# Segment counting — what the caller is billed for
# ---------------------------------------------------------------------------


def test_ascii_segments_follow_gsm7_sizes():
    adapter = build_messaging(config())
    assert adapter.segments("") == 1
    assert adapter.segments("a" * 160) == 1
    assert adapter.segments("a" * 161) == 2
    assert adapter.segments("a" * 306) == 2  # 153 usable per concatenated segment
    assert adapter.segments("a" * 307) == 3


def test_one_non_ascii_character_halves_the_whole_message():
    """A single Cyrillic letter forces UCS-2 for every character in the body."""
    adapter = build_messaging(config())
    assert adapter.segments("a" * 70) == 1
    assert adapter.segments("a" * 69 + "я") == 1
    assert adapter.segments("a" * 70 + "я") == 2


# ---------------------------------------------------------------------------
# Twilio: the request that goes out
# ---------------------------------------------------------------------------


async def test_send_posts_to_the_messages_endpoint(recorder):
    adapter = build_messaging(config())
    assert await adapter.send(to="+15551112222", body="hi") == "SM-1"

    request = recorder.requests[-1]
    assert (
        str(request.url)
        == f"{TWILIO_API_ROOT}/2010-04-01/Accounts/AC-test/Messages.json"
    )
    assert recorder.form == {"To": "+15551112222", "Body": "hi", "From": "+15550000000"}


async def test_a_per_message_sender_wins_over_the_row(recorder):
    adapter = build_messaging(config())
    await adapter.send(to="+15551112222", body="hi", sender="VOXLINE")
    assert recorder.form["From"] == "VOXLINE"


async def test_a_sender_pool_is_used_when_no_sender_is_configured(recorder):
    adapter = build_messaging(config(sender=None, sender_pool_id="MG-1"))
    await adapter.send(to="+15551112222", body="hi")
    form = recorder.form
    assert form["MessagingServiceSid"] == "MG-1"
    assert "From" not in form


async def test_a_status_url_is_passed_through(recorder):
    adapter = build_messaging(config())
    await adapter.send(to="+15551112222", body="hi", status_url="https://x.invalid/s")
    assert recorder.form["StatusCallback"] == "https://x.invalid/s"


async def test_send_refuses_without_what_it_needs(recorder):
    no_creds = build_messaging(config(account_id=None, auth_token=None))
    with pytest.raises(ValueError, match="account_id"):
        await no_creds.send(to="+15551112222", body="hi")

    no_sender = build_messaging(config(sender=None))
    with pytest.raises(ValueError, match="sender"):
        await no_sender.send(to="+15551112222", body="hi")

    assert recorder.requests == []  # nothing reached the network


async def test_a_rejection_surfaces_as_an_http_error(recording):
    recording(status=400, payload={"message": "unverified number"})

    adapter = build_messaging(config())
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.send(to="+15551112222", body="hi")


async def test_region_pinning_moves_the_api_root(recorder):
    adapter = build_messaging(config(options={"region": "ie1", "edge": "dublin"}))
    await adapter.send(to="+15551112222", body="hi")
    assert str(recorder.requests[-1].url).startswith(
        "https://api.dublin.ie1.twilio.com/"
    )


async def test_a_control_url_overrides_everything(recorder):
    adapter = build_messaging(
        config(control_url="http://127.0.0.1:59110/twilio/", options={"region": "ie1"})
    )
    await adapter.send(to="+15551112222", body="hi")
    assert str(recorder.requests[-1].url).startswith(
        "http://127.0.0.1:59110/twilio/2010-04-01/"
    )


# ---------------------------------------------------------------------------
# Mamonty: the request that goes out
# ---------------------------------------------------------------------------


#: What the vendor answers for one accepted message.
ACCEPTED = {
    "status": "success",
    "data": [
        {"message": "hi", "id": 370506708, "status": "sent", "phone": "79991112222"}
    ],
}


def mamonty(**overrides) -> MessagingConfig:
    defaults = {
        "adapter": MessagingAdapterEnum.mamonty,
        "auth_token": "key-test",
        "sender": "VIRTA",
    }
    defaults.update(overrides)
    return MessagingConfig(**defaults)


def test_the_registry_resolves_mamonty():
    assert isinstance(build_messaging(mamonty()), MamontyMessagingAdapter)


def test_mamonty_declares_what_it_can_do():
    adapter = build_messaging(mamonty())
    assert adapter.capabilities.supports_delivery_status is True
    assert adapter.capabilities.supports_alphanumeric_sender is True
    assert adapter.capabilities.supports_sender_pool is False


async def test_mamonty_send_posts_one_message_batch(recording):
    recorder = recording(payload=ACCEPTED)
    adapter = build_messaging(mamonty())

    assert await adapter.send(to="+79991112222", body="hi") == "370506708"

    assert str(recorder.requests[-1].url) == f"{MAMONTY_API_ROOT}/apiSms/create"
    assert recorder.json == {
        "apiKey": "key-test",
        # The vendor's numbers are bare digits, never E.164.
        "sms": [
            {
                "channel": "char",
                "phone": "79991112222",
                "text": "hi",
                "sender": "VIRTA",
            }
        ],
    }


async def test_a_status_url_rides_along_as_the_webhook_url(recording):
    recorder = recording(payload=ACCEPTED)
    adapter = build_messaging(mamonty())

    await adapter.send(to="+79991112222", body="hi", status_url="https://x.invalid/s")

    assert recorder.json["webhookUrl"] == "https://x.invalid/s"


async def test_no_status_url_means_no_webhook_key_at_all(recording):
    recorder = recording(payload=ACCEPTED)
    adapter = build_messaging(mamonty())

    await adapter.send(to="+79991112222", body="hi")

    assert "webhookUrl" not in recorder.json


async def test_a_per_message_sender_wins_over_the_mamonty_row(recording):
    recorder = recording(payload=ACCEPTED)
    adapter = build_messaging(mamonty())

    await adapter.send(to="+79991112222", body="hi", sender="VOXLINE")

    assert recorder.json["sms"][0]["sender"] == "VOXLINE"


async def test_the_channel_is_inferred_from_whether_a_sender_is_set(recording):
    recorder = recording(payload=ACCEPTED)

    await build_messaging(mamonty()).send(to="+79991112222", body="hi")
    assert recorder.json["sms"][0]["channel"] == "char"

    # A short code carries no sender name, and the vendor accepts none.
    await build_messaging(mamonty(sender=None)).send(to="+79991112222", body="hi")
    message = recorder.json["sms"][0]
    assert message["channel"] == "digit"
    assert "sender" not in message


async def test_an_explicit_channel_wins_over_the_inference(recording):
    recorder = recording(payload=ACCEPTED)
    adapter = build_messaging(mamonty(options={"channel": "digit"}))

    await adapter.send(to="+79991112222", body="hi")

    message = recorder.json["sms"][0]
    assert message["channel"] == "digit"
    assert "sender" not in message


def test_a_messenger_channel_is_refused_when_the_route_is_built():
    """A row configured for Viber fails naming itself, not mid-send."""
    with pytest.raises(ValueError, match="not an SMS channel"):
        build_messaging(mamonty(options={"channel": "viber"}))


async def test_mamonty_send_refuses_without_what_it_needs(recording):
    recorder = recording(payload=ACCEPTED)

    no_key = build_messaging(mamonty(auth_token=None))
    with pytest.raises(ValueError, match="apiKey"):
        await no_key.send(to="+79991112222", body="hi")

    no_sender = build_messaging(mamonty(sender=None, options={"channel": "char"}))
    with pytest.raises(ValueError, match="needs a sender"):
        await no_sender.send(to="+79991112222", body="hi")

    assert recorder.requests == []  # nothing reached the network


async def test_an_application_level_failure_carries_the_vendors_words(recording):
    """The vendor reports refusals with HTTP 200 and a non-success status."""
    recording(payload={"status": "error", "message": "низкий баланс"})
    adapter = build_messaging(mamonty())

    with pytest.raises(ValueError, match="низкий баланс"):
        await adapter.send(to="+79991112222", body="hi")


async def test_a_refusal_inside_a_success_envelope_is_still_a_refusal(recording):
    """The live shape: HTTP 200, "status": "success", the rejection in the entry.

    Asking for a channel the account does not have comes back like this — no
    id anywhere, and the only thing naming the problem is the entry's own
    ``errorDescription``, which is what has to reach the operator.
    """
    recording(
        payload={
            "status": "success",
            "data": [
                {
                    "currency": "EUR",
                    "errorDescription": (
                        "Access denied to create [digit] SMS or the channel "
                        "doesn't exist"
                    ),
                    "errorCode": "channel",
                    "status": "error",
                    "phone": "4915888620339",
                }
            ],
        }
    )
    adapter = build_messaging(mamonty(options={"channel": "digit"}))

    with pytest.raises(ValueError, match=r"Access denied .*\[channel\]"):
        await adapter.send(to="+4915888620339", body="hi")


async def test_a_refusal_does_not_report_the_sms_text_as_the_reason(recording):
    """``message`` on an entry is the body we sent, never why it was refused."""
    recording(
        payload={
            "status": "success",
            "data": [{"status": "error", "message": "hi", "phone": "79991112222"}],
        }
    )
    adapter = build_messaging(mamonty())

    with pytest.raises(ValueError, match="refused") as refusal:
        await adapter.send(to="+79991112222", body="hi")
    assert "'message': 'hi'" in str(refusal.value)  # the raw body, not "hi" alone


async def test_an_empty_acceptance_is_a_failure_not_a_send(recording):
    recording(payload={"status": "success", "data": []})
    adapter = build_messaging(mamonty())

    with pytest.raises(ValueError, match="accepted nothing"):
        await adapter.send(to="+79991112222", body="hi")


async def test_a_control_url_overrides_the_mamonty_root(recording):
    recorder = recording(payload=ACCEPTED)
    adapter = build_messaging(mamonty(control_url="http://127.0.0.1:59110/mamonty/"))

    await adapter.send(to="+79991112222", body="hi")

    assert (
        str(recorder.requests[-1].url) == "http://127.0.0.1:59110/mamonty/apiSms/create"
    )


# ---------------------------------------------------------------------------
# Cleared options — what a configuration form sends for a blank input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": ""},
        {"timeout": None},
        {"channel": ""},
        {"channel": None},
        {"channel": "", "timeout": "", "status_url_base": ""},
    ],
)
async def test_blank_mamonty_options_read_as_unset(options, recording):
    """A cleared input arrives as "" or null, not as an absent key.

    Taken literally, ``float("")`` raises past the caller's handling and an
    empty channel is "not an SMS channel" — a blank box in the admin UI would
    500 the send it configures.
    """
    recorder = recording(payload=ACCEPTED)
    adapter = build_messaging(mamonty(options=options))

    await adapter.send(to="+79991112222", body="hi")

    # Fell back to the defaults rather than blowing up on the empty string.
    assert recorder.json["sms"][0]["channel"] == "char"


async def test_blank_twilio_options_read_as_unset(recording):
    recorder = recording(payload={"sid": "SM-1"})
    adapter = build_messaging(config(options={"region": "", "edge": "", "timeout": ""}))

    await adapter.send(to="+15551112222", body="hi")

    # An empty region would otherwise build "https://api..twilio.com".
    assert str(recorder.requests[-1].url).startswith(f"{TWILIO_API_ROOT}/")


# ---------------------------------------------------------------------------
# Delivery callbacks — the half of the contract that comes back
# ---------------------------------------------------------------------------


#: Captured from the wire: what Mamonty actually posts to a webhookUrl.
LIVE_CALLBACK = [
    {
        "id": 313913312,
        "status": "error",
        "phone": "359899004167",
        "cost": 0.0,
        "error_description": "Routing error",
        "created_at": 1790079468,
        "updated_at": 1790079474,
    }
]


def test_mamonty_reads_the_callback_it_really_receives():
    verdict = build_messaging(mamonty()).parse_callback(
        LIVE_CALLBACK, provider_ref="313913312"
    )
    assert verdict.status is MessageStatusEnum.failed
    assert verdict.error == "Routing error"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sent", MessageStatusEnum.sent),
        ("delivered", MessageStatusEnum.delivered),
        # Strictly later than delivered, and we have no rank beyond it.
        ("read", MessageStatusEnum.delivered),
        ("not_delivered", MessageStatusEnum.undelivered),
        ("error", MessageStatusEnum.failed),
        ("low_balance", MessageStatusEnum.failed),
        ("low_partner_balance", MessageStatusEnum.failed),
        ("rejected", MessageStatusEnum.canceled),
        # Provisional — they say nothing our own row does not already know.
        ("created", None),
        ("moderation", None),
        ("planned", None),
        ("", None),
    ],
)
def test_the_mamonty_status_vocabulary(raw, expected):
    verdict = build_messaging(mamonty()).parse_callback(
        [{"id": 1, "status": raw}], provider_ref="1"
    )
    assert verdict.status is expected


def test_a_batch_verdict_is_picked_out_by_id():
    """The body is a list, and a verdict written onto the wrong row is silent."""
    batch = [
        {"id": 111, "status": "delivered"},
        {"id": 222, "status": "not_delivered"},
    ]
    adapter = build_messaging(mamonty())

    assert adapter.parse_callback(batch, provider_ref="222").status is (
        MessageStatusEnum.undelivered
    )
    # A batch naming only other people's messages is not ours to write.
    assert adapter.parse_callback(batch, provider_ref="333").status is None


def test_a_lone_unidentified_entry_is_still_believed():
    """The id is how a batch is resolved, not a precondition for a verdict."""
    verdict = build_messaging(mamonty()).parse_callback(
        [{"status": "delivered"}], provider_ref="313913312"
    )
    assert verdict.status is MessageStatusEnum.delivered


def test_mamonty_signs_nothing_so_the_url_hmac_is_the_lock():
    """Observed on the wire: no signature header, only Sentry tracing."""
    adapter = build_messaging(mamonty())
    assert adapter.verify_callback(url=None, headers={}, form=None) is True


def test_twilio_holds_a_callback_to_its_signature():
    adapter = build_messaging(config())
    url = "https://hooks.invalid/sms/msg-1/status?t=abc"
    form = {"MessageStatus": "delivered", "MessageSid": "SM-1"}
    presented = signature("token-test", url, form)

    assert adapter.verify_callback(
        url=url, headers={"X-Twilio-Signature": presented}, form=form
    )
    # A captured URL replayed with a rewritten status is what this stops.
    assert not adapter.verify_callback(
        url=url,
        headers={"X-Twilio-Signature": presented},
        form={**form, "MessageStatus": "failed"},
    )
    assert not adapter.verify_callback(url=url, headers={}, form=form)


def test_twilio_fails_closed_when_the_signed_url_cannot_be_rebuilt():
    """No public base means the check cannot run, which is not the same as passing."""
    adapter = build_messaging(config())
    assert (
        adapter.verify_callback(
            url=None, headers={"X-Twilio-Signature": "anything"}, form={}
        )
        is False
    )


def test_twilio_reads_its_own_vocabulary():
    adapter = build_messaging(config())

    verdict = adapter.parse_callback(
        {"MessageStatus": "delivered", "MessageSid": "SM-1"}, provider_ref="SM-1"
    )
    assert verdict.status is MessageStatusEnum.delivered
    assert verdict.error is None

    failed = adapter.parse_callback(
        {"MessageStatus": "failed", "ErrorCode": "30008", "ErrorMessage": "unknown"}
    )
    assert failed.status is MessageStatusEnum.failed
    assert failed.error == "30008 unknown"

    # Provisional dispositions carry nothing our row does not already have.
    assert adapter.parse_callback({"MessageStatus": "queued"}).status is None


def test_a_twilio_callback_naming_another_message_is_dropped():
    adapter = build_messaging(config())
    verdict = adapter.parse_callback(
        {"MessageStatus": "delivered", "MessageSid": "SM-other"}, provider_ref="SM-1"
    )
    assert verdict.status is None


# ---------------------------------------------------------------------------
# The shared Twilio helpers
# ---------------------------------------------------------------------------


def test_api_root_defaults_and_pinning():
    assert api_root() == TWILIO_API_ROOT
    assert api_root(region="ie1") == "https://api.ie1.twilio.com"
    assert api_root(edge="dublin") == "https://api.dublin.twilio.com"
    assert api_root("https://double.invalid/") == "https://double.invalid"


def test_a_signature_covers_the_parameters_not_just_the_url():
    url = "https://hooks.invalid/v1/media/catt-1/status?t=abc"
    params = {"CallStatus": "busy", "CallSid": "CA-1"}
    presented = signature("token", url, params)

    assert verify_signature("token", url, params, presented)
    # Rewriting a parameter on a captured URL breaks it — the whole point.
    assert not verify_signature(
        "token", url, {**params, "CallStatus": "failed"}, presented
    )
    assert not verify_signature("token", url + "x", params, presented)
    assert not verify_signature("other-token", url, params, presented)
    assert not verify_signature("token", url, params, None)
    assert not verify_signature("", url, params, presented)


def test_the_signature_matches_twilios_published_example():
    """Twilio's own worked example, so the algorithm is pinned to theirs."""
    url = "https://example.com/myapp.php?foo=1&bar=2"
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+14158675310",
        "Digits": "1234",
        "From": "+14158675310",
        "To": "+18005551212",
    }
    assert signature("12345", url, params) == "L/OH5YylLD5NRKLltdqwSvS0BnU="
