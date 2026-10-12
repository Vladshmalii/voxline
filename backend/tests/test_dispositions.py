"""The provider status -> attempt result mapping: pure, every branch."""

from __future__ import annotations

import pytest

from src.application.worker.dispositions import classify, extract
from src.common.enums.engine import CallStatusEnum
from src.schemas.campaign import RetryPolicy

S = CallStatusEnum


def _classify(**payload):
    return classify(extract(payload))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"call_status": "ringing"},
        {"call_status": "trying"},
        {"call_status": "early-media"},
        {"call_status": "in-progress"},
        {"CallStatus": "initiated"},
        {"CallStatus": "queued"},
    ],
)
def test_provisional_statuses_are_not_recorded(payload):
    assert classify(extract(payload)) is None


def test_completed():
    assert _classify(call_status="completed").status == S.completed
    # A SIP code on a completed call changes nothing.
    assert _classify(call_status="completed", sip_status=200).status == S.completed


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"call_status": "no-answer"}, S.no_answer),
        ({"CallStatus": "no-answer"}, S.no_answer),
        ({"call_status": "no_answer"}, S.no_answer),
        ({"call_status": "failed", "sip_status": 480}, S.no_answer),
        ({"call_status": "failed", "sip_status": 408}, S.no_answer),
        ({"call_status": "busy"}, S.busy),
        ({"call_status": "failed", "sip_status": 486}, S.busy),
        ({"call_status": "failed", "sip_status": 600}, S.busy),
        ({"call_status": "failed", "sip_status": 603}, S.rejected),
        ({"call_status": "canceled", "sip_status": 603}, S.rejected),
        ({"call_status": "failed", "sip_status": 404}, S.invalid_number),
        ({"call_status": "failed", "sip_status": 484}, S.invalid_number),
        ({"CallStatus": "failed", "SipResponseCode": "404"}, S.invalid_number),
        ({"call_status": "canceled"}, S.canceled),
    ],
)
def test_result_mapping(payload, expected):
    disposition = classify(extract(payload))
    assert disposition.status == expected
    assert disposition.error is None
    assert not disposition.unknown


@pytest.mark.parametrize(
    "payload",
    [
        {"call_status": "failed", "sip_status": 403, "sip_reason": "Forbidden"},
        {"call_status": "failed", "sip_status": 503},
        {"call_status": "no-answer", "sip_status": 500},
        {"call_status": "failed", "sip_status": 402},
        {"call_status": "failed"},
    ],
)
def test_failures_carry_a_human_error(payload):
    disposition = classify(extract(payload))
    assert disposition.status == S.failed
    assert disposition.error and "provider reported" in disposition.error
    assert not disposition.unknown


def test_failure_error_includes_sip_code_and_reason():
    disposition = _classify(call_status="failed", sip_status=403, sip_reason="Forbidden")
    assert "403 Forbidden" in disposition.error


def test_unknown_status_fails_with_the_raw_value():
    disposition = _classify(call_status="Exploded")
    assert disposition.status == S.failed
    assert disposition.error == "unknown provider status: exploded"
    assert disposition.unknown


def test_extract_reads_both_dialects():
    jambonz = extract(
        {"call_status": "Failed", "sip_status": 486, "sip_reason": "Busy Here"}
    )
    assert (jambonz.status, jambonz.sip_code, jambonz.reason) == (
        "failed",
        486,
        "Busy Here",
    )
    assert jambonz.reason_text == "486 Busy Here"

    twilio = extract({"CallStatus": "busy", "SipResponseCode": "486"})
    assert (twilio.status, twilio.sip_code, twilio.reason) == ("busy", 486, None)
    assert twilio.reason_text == "486"

    junk = extract({"call_status": "failed", "sip_status": "n/a"})
    assert junk.sip_code is None and junk.reason_text is None


def test_retry_policy_covers_the_new_statuses():
    policy = RetryPolicy(no_answer_delay_seconds=111)
    assert policy.delay_for(S.rejected) == 111
    assert policy.delay_for(S.invalid_number) is None
