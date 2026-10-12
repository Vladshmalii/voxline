"""dial_call and sweep_calls: the claims and repairs that make scaling safe."""

from __future__ import annotations

from sqlalchemy import text, update

from src.application.worker import registry
from src.application.worker.tasks import dial_call, sweep_calls
from src.common.enums.campaign import CallLifecycleEnum
from src.common.enums.engine import CallDirectionEnum, CallStatusEnum
from src.core.control import directory
from src.models.call import Call, CallAttempt
from src.repositories.call import CallAttemptCRUD, CallCRUD
from src.repositories.client import ClientCRUD
from src.settings import SETTINGS
from tests.support import queue_depth, seed_stack


async def _queued_attempt(
    session, agent_id: int, to: str = "+15551112222"
) -> CallAttempt:
    client = await ClientCRUD(session).upsert_by_phone(to)
    call = await CallCRUD(session).create(
        {
            "client_id": client.id,
            "agent_id": agent_id,
            "direction": CallDirectionEnum.outbound,
            "status": CallLifecycleEnum.calling,
            "from_number": "+15550000001",
            "attempts_made": 1,
        }
    )
    attempt = await CallAttemptCRUD(session).create(
        {"call_id": call.id, "seq": 1, "status": CallStatusEnum.queued}
    )
    await session.commit()
    return attempt


async def _attempt_status(session, attempt_id: int) -> CallAttempt:
    """Fresh row state by plain id — expire_all() invalidates every instance
    the test still holds, so callers must pass captured ints, not attributes
    of expired ORM objects (that access is sync IO → MissingGreenlet)."""
    session.expire_all()
    return await CallAttemptCRUD(session).get_one_or_none(CallAttempt.id == attempt_id)


async def test_dial_claims_and_originates(org_uuid, session, fake_adapter):
    stack = await seed_stack(session, media_url_base="wss://vpc-hooks/api/v1")
    attempt = await _queued_attempt(session, stack.agent.id)

    await dial_call(org_uuid=org_uuid, attempt_id=attempt.id)

    row = await _attempt_status(session, attempt.id)
    assert row.status == CallStatusEnum.dialing
    assert row.provider_ref == f"ref-{row.uuid}"

    assert len(fake_adapter.dials) == 1
    dial = fake_adapter.dials[0]
    assert dial["to"] == "+15551112222"  # the client's phone, via the parent call
    token = registry.media_token(SETTINGS.secret_key, str(row.uuid))
    # Media URL: per-trunk base (the VPC one), the attempt uuid, the HMAC token.
    assert dial["media_url"] == f"wss://vpc-hooks/api/v1/media/{row.uuid}?t={token}"
    # Dispositions go to the same host over https.
    assert dial["status_url"].startswith(
        f"https://vpc-hooks/api/v1/media/{row.uuid}/status"
    )
    # The handoff is registered for the media socket that will arrive.
    assert await registry.claim(str(row.uuid)) == {
        "org_uuid": org_uuid,
        "call_id": attempt.id,
    }


async def test_duplicate_delivery_dials_once(org_uuid, session, fake_adapter):
    """At-most-once by claim, not by broker: the second delivery loses the UPDATE."""
    stack = await seed_stack(session)
    attempt = await _queued_attempt(session, stack.agent.id)

    await dial_call(org_uuid=org_uuid, attempt_id=attempt.id)
    await dial_call(org_uuid=org_uuid, attempt_id=attempt.id)

    assert len(fake_adapter.dials) == 1


async def test_cancel_beats_the_dial(org_uuid, session, fake_adapter):
    stack = await seed_stack(session)
    attempt = await _queued_attempt(session, stack.agent.id)
    call_id = attempt.call_id
    assert await CallCRUD(session).cancel(call_id)
    await session.commit()

    await dial_call(org_uuid=org_uuid, attempt_id=attempt.id)

    assert fake_adapter.dials == []
    assert (
        await _attempt_status(session, attempt.id)
    ).status == CallStatusEnum.canceled
    assert (
        await CallCRUD(session).get_one_or_none(Call.id == call_id)
    ).status == CallLifecycleEnum.canceled


async def test_dial_failure_is_recorded_not_raised(org_uuid, session, fake_adapter):
    stack = await seed_stack(session)
    attempt = await _queued_attempt(session, stack.agent.id)
    fake_adapter.fail_with = "carrier rejected the INVITE"

    await dial_call(org_uuid=org_uuid, attempt_id=attempt.id)

    row = await _attempt_status(session, attempt.id)
    assert row.status == CallStatusEnum.failed
    assert "carrier rejected" in row.error
    # The handoff was discarded: nothing will ever legitimately connect.
    assert await registry.claim(str(row.uuid)) is None


async def test_at_capacity_leaves_the_row_queued(
    org_uuid, session, fake_adapter, monkeypatch
):
    stack = await seed_stack(session)
    attempt = await _queued_attempt(session, stack.agent.id)
    monkeypatch.setattr(SETTINGS.call_worker, "max_concurrent_calls", 0)

    await dial_call(org_uuid=org_uuid, attempt_id=attempt.id)

    assert fake_adapter.dials == []
    assert (await _attempt_status(session, attempt.id)).status == CallStatusEnum.queued


async def test_sweep_heals_every_strandable_state(
    org_uuid, session, fake_adapter, monkeypatch
):
    stack = await seed_stack(session)

    lost_queued = await _queued_attempt(session, stack.agent.id, to="+15551110001")
    stranded_dialing = await _queued_attempt(session, stack.agent.id, to="+15551110002")
    dead_in_progress = await _queued_attempt(session, stack.agent.id, to="+15551110003")
    healthy_in_progress = await _queued_attempt(
        session, stack.agent.id, to="+15551110004"
    )

    # Age/state surgery: explicit updated_at wins over onupdate.
    await session.execute(
        update(CallAttempt)
        .where(CallAttempt.id == lost_queued.id)
        .values(updated_at=text("now() - INTERVAL '2 minutes'"))
    )
    await session.execute(
        update(CallAttempt)
        .where(CallAttempt.id == stranded_dialing.id)
        .values(
            status=CallStatusEnum.dialing,
            updated_at=text("now() - INTERVAL '10 minutes'"),
        )
    )
    for attempt in (dead_in_progress, healthy_in_progress):
        await session.execute(
            update(CallAttempt)
            .where(CallAttempt.id == attempt.id)
            .values(status=CallStatusEnum.in_progress)
        )
    await session.commit()
    await registry.mark_live(str(healthy_in_progress.uuid))

    async def fake_orgs(only_active: bool = True):
        return [{"uuid": org_uuid}]

    monkeypatch.setattr(directory, "organizations_list", fake_orgs)

    ids = {
        "lost": lost_queued.id,
        "stranded": stranded_dialing.id,
        "dead": dead_in_progress.id,
        "healthy": healthy_in_progress.id,
    }

    await sweep_calls()

    statuses = {
        name: (await _attempt_status(session, attempt_id)).status
        for name, attempt_id in ids.items()
    }
    assert statuses["stranded"] == CallStatusEnum.failed
    assert statuses["dead"] == CallStatusEnum.failed  # liveness lock missing
    assert statuses["healthy"] == CallStatusEnum.in_progress  # lock held → untouched
    assert statuses["lost"] == CallStatusEnum.queued  # re-enqueued, not mutated

    assert await queue_depth() == 1  # exactly the lost queued attempt


async def test_sweep_is_idempotent(org_uuid, session, fake_adapter, monkeypatch):
    stack = await seed_stack(session)
    attempt = await _queued_attempt(session, stack.agent.id)
    await session.execute(
        update(CallAttempt)
        .where(CallAttempt.id == attempt.id)
        .values(
            status=CallStatusEnum.dialing,
            updated_at=text("now() - INTERVAL '10 minutes'"),
        )
    )
    await session.commit()
    attempt_id = attempt.id

    async def fake_orgs(only_active: bool = True):
        return [{"uuid": org_uuid}]

    monkeypatch.setattr(directory, "organizations_list", fake_orgs)

    await sweep_calls()
    first = (await _attempt_status(session, attempt_id)).error
    await sweep_calls()  # overlapping schedulers cost queries, not correctness

    row = await _attempt_status(session, attempt_id)
    assert row.status == CallStatusEnum.failed and row.error == first
