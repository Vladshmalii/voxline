"""analyze_attempt: guarded writes, the recall handoff, retry-friendly failure.

The LLM is faked at the service seam (``analysis.analyze_transcript``); what's
under test is the task's row handling, which is what makes repeat delivery the
retry mechanism.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.application.services import analysis
from src.application.services.analysis import AnalysisError, AnalysisResult
from src.application.worker.tasks import analyze_attempt
from src.common.enums.campaign import CallOutcomeEnum
from src.common.enums.engine import CallStatusEnum
from src.models.call import Call, CallAttempt
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.provider import ModelCRUD
from tests.support import seed_stack
from tests.worker.test_dispatch import TALK, _call, _with_attempt


@pytest.fixture
def fake_llm(monkeypatch):
    """Records transcripts; returns a canned result or raises."""
    calls: list[str] = []
    state = {
        "result": AnalysisResult(summary="Спасибо, интересно.", outcome="interested")
    }

    async def fake(ttt, transcript, *, language, now=None, offers=()):
        calls.append(transcript)
        state["offers"] = offers
        state["ttt"] = ttt
        if isinstance(state["result"], Exception):
            raise state["result"]
        return state["result"]

    monkeypatch.setattr(analysis, "analyze_transcript", fake)
    state["transcripts"] = calls
    return state


async def _fresh_attempt(session, attempt_id: int) -> CallAttempt:
    session.expire_all()
    return await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == attempt_id)


async def test_analysis_lands_on_the_attempt(org_uuid, session, fake_llm):
    stack = await seed_stack(session)
    call = await _call(session, stack.agent.id, "+15551110030")
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)

    row = await _fresh_attempt(session, attempt.id)
    assert row.outcome == CallOutcomeEnum.interested
    assert row.summary == "Спасибо, интересно."
    assert fake_llm["transcripts"] == ["agent: Hi!\ncaller: Hello."]


async def test_named_recall_time_reaches_the_call(org_uuid, session, fake_llm):
    stack = await seed_stack(session)
    call = await _call(session, stack.agent.id, "+15551110031")
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )
    call_id = call.id  # plain int, safe to use after expire_all()
    recall_at = datetime.now() + timedelta(hours=3)
    fake_llm["result"] = AnalysisResult(
        summary="Просил перезвонить.", outcome="call_later", recall_at=recall_at
    )

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)

    session.expire_all()
    row = await CallCRUD(session).get_one_or_none(Call.id == call_id)
    assert row.next_attempt_at == recall_at  # for settle to pick up


async def test_repeat_delivery_and_settled_rows_are_skipped(
    org_uuid, session, fake_llm
):
    stack = await seed_stack(session)
    call = await _call(session, stack.agent.id, "+15551110032")
    attempt = await _with_attempt(
        session,
        call,
        CallStatusEnum.completed,
        messages=TALK,
        outcome=CallOutcomeEnum.interested,  # already analyzed
    )

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)

    assert fake_llm["transcripts"] == []  # no second LLM call


async def test_bonuses_reach_analysis_as_offer_labels(org_uuid, session, fake_llm):
    stack = await seed_stack(session)
    call = await _call(
        session,
        stack.agent.id,
        "+15551110034",
        bonuses=[{"title": "50% reload"}, {"name": "free spins"}],
    )
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)

    assert fake_llm["offers"] == ["50% reload", "free spins"]


async def test_selected_offer_lands_on_the_attempt(org_uuid, session, fake_llm):
    stack = await seed_stack(session)
    call = await _call(
        session, stack.agent.id, "+15551110035", bonuses=[{"title": "50% reload"}]
    )
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )
    fake_llm["result"] = AnalysisResult(
        summary="Согласился.", outcome="converted", selected_offer="50% reload"
    )

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)

    row = await _fresh_attempt(session, attempt.id)
    assert row.selected_offer == "50% reload"


async def test_failure_leaves_the_row_for_the_next_tick(org_uuid, session, fake_llm):
    stack = await seed_stack(session)
    call = await _call(session, stack.agent.id, "+15551110033")
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )
    fake_llm["result"] = AnalysisError("endpoint unreachable")

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)  # must not raise

    row = await _fresh_attempt(session, attempt.id)
    assert row.outcome is None and row.summary is None


async def test_call_llm_analyzes_when_no_analysis_model(org_uuid, session, fake_llm):
    stack = await seed_stack(session)
    call = await _call(session, stack.agent.id, "+15551110036")
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)

    assert fake_llm["ttt"].model.code == "llm-32b"  # the agent's own LLM


async def test_flagged_analysis_model_serves_every_agent(org_uuid, session, fake_llm):
    stack = await seed_stack(session)
    await ModelCRUD(session).create(
        {
            "name": "analyst",
            "kind": "ttt",
            "adapter": "openai_compatible",
            "code": "analyst-70b",
            "is_active": True,
            "is_analysis": True,
            "provider_id": stack.provider.id,
        }
    )
    call = await _call(session, stack.agent.id, "+15551110037")
    attempt = await _with_attempt(
        session, call, CallStatusEnum.completed, messages=TALK
    )

    await analyze_attempt(org_uuid=org_uuid, attempt_id=attempt.id)

    assert fake_llm["ttt"].model.code == "analyst-70b"
    assert fake_llm["ttt"].model.provider.url == stack.provider.url
