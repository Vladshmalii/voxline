"""Post-call analysis parsing: transcripts without scaffolding, tolerant JSON.

Pure-python checks of ``application/services/analysis.py`` (in the api suite
for its interpreter; no DB use).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.application.services.analysis import (
    AnalysisError,
    offer_label,
    parse_analysis,
    render_transcript,
)
from src.common.enums.campaign import CallOutcomeEnum

NOW = datetime(2026, 9, 8, 12, 0)


def test_transcript_keeps_turns_and_drops_scaffolding():
    messages = [
        {"role": "system", "content": "You are a voice agent."},
        {"role": "user", "content": "Customer profile for this call:\nName: Anna"},
        {"role": "user", "content": "Greet the customer."},  # the kickoff
        {"role": "assistant", "content": "Hi Anna!"},
        {"role": "user", "content": "Who is this?"},
        {"role": "event", "event": "language_switched"},
    ]
    transcript = render_transcript(
        messages, scaffolding=frozenset({"Greet the customer."})
    )
    assert transcript == "agent: Hi Anna!\ncaller: Who is this?"


def test_parse_survives_fences_and_prose():
    reply = 'Here is the analysis:\n```json\n{"summary": "Клиент занят.", "outcome": "call_later", "recall_at": null}\n```'
    result = parse_analysis(reply, now=NOW)
    assert result.outcome == CallOutcomeEnum.call_later
    assert result.summary == "Клиент занят." and result.recall_at is None


def test_parse_rejects_unknown_and_unassignable_outcomes():
    with pytest.raises(AnalysisError, match="unknown outcome"):
        parse_analysis('{"summary": "x", "outcome": "maybe"}', now=NOW)
    # no_answer is telephony-derived; the model must not assign it.
    with pytest.raises(AnalysisError, match="unknown outcome"):
        parse_analysis('{"summary": "x", "outcome": "no_answer"}', now=NOW)
    with pytest.raises(AnalysisError, match="no JSON"):
        parse_analysis("the call went fine", now=NOW)


def test_recall_time_is_clamped_and_bound_to_call_later():
    good = parse_analysis(
        '{"summary": "s", "outcome": "call_later", "recall_at": "2026-09-09T17:00"}',
        now=NOW,
    )
    assert good.recall_at == datetime(2026, 9, 9, 17, 0)

    past = parse_analysis(
        '{"summary": "s", "outcome": "call_later", "recall_at": "2026-09-01T10:00"}',
        now=NOW,
    )
    assert past.recall_at is None  # falls back to the retry policy

    too_far = parse_analysis(
        '{"summary": "s", "outcome": "call_later", "recall_at": "2027-09-09T17:00"}',
        now=NOW,
    )
    assert too_far.recall_at is None

    garbled = parse_analysis(
        '{"summary": "s", "outcome": "call_later", "recall_at": "tomorrow-ish"}',
        now=NOW,
    )
    assert garbled.recall_at is None

    not_call_later = parse_analysis(
        '{"summary": "s", "outcome": "interested", "recall_at": "2026-09-09T17:00"}',
        now=NOW,
    )
    assert not_call_later.recall_at is None


def test_summary_is_capped():
    result = parse_analysis(
        '{"summary": "' + "x" * 5000 + '", "outcome": "interested"}', now=NOW
    )
    assert len(result.summary) == 1000


def test_offer_label_prefers_title_then_name_then_id():
    assert offer_label({"title": "50% reload", "name": "x", "id": 1}) == "50% reload"
    assert offer_label({"name": "welcome bonus", "id": 1}) == "welcome bonus"
    assert offer_label({"id": 42}) == "42"
    assert offer_label({"amount": 10}) == '{"amount": 10}'
    assert offer_label("free spins") == "free spins"


def test_selected_offer_must_match_one_of_the_offered_labels():
    offers = ["50% reload", "free spins"]

    picked = parse_analysis(
        '{"summary": "s", "outcome": "interested", "selected_offer": "free spins"}',
        now=NOW,
        offers=offers,
    )
    assert picked.selected_offer == "free spins"

    none_picked = parse_analysis(
        '{"summary": "s", "outcome": "not_interested", "selected_offer": null}',
        now=NOW,
        offers=offers,
    )
    assert none_picked.selected_offer is None

    hallucinated = parse_analysis(
        '{"summary": "s", "outcome": "interested", "selected_offer": "a yacht"}',
        now=NOW,
        offers=offers,
    )
    assert hallucinated.selected_offer is None

    no_offers_on_this_call = parse_analysis(
        '{"summary": "s", "outcome": "interested", "selected_offer": "free spins"}',
        now=NOW,
        offers=[],
    )
    assert no_offers_on_this_call.selected_offer is None
