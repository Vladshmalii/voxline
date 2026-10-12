import csv
import io
from datetime import datetime, timedelta

import openpyxl
import pytest

from src.common.enums.campaign import CallLifecycleEnum, CallOutcomeEnum, SentimentEnum
from src.common.enums.engine import CallDirectionEnum, CallStatusEnum
from src.controller.dependencies.permission import _get_role
from src.core.enums import CallRoleEnum, SharedRoleEnum
from src.models.call import Call, CallAttempt
from src.models.campaign import Campaign
from src.models.client import Client
from tests.support import seed_stack


@pytest.fixture
async def history(session):
    first = await seed_stack(session)
    second = await seed_stack(session)
    campaigns = [
        Campaign(name="current", agent_id=first.agent.id),
        Campaign(name="archived", agent_id=second.agent.id, is_archived=True),
    ]
    clients = [
        Client(name="Мария", phone="+49123456789"),
        Client(name="Борис", phone="+49123450000"),
    ]
    session.add_all([*campaigns, *clients])
    await session.flush()
    dates = [
        "2026-09-21T23:59:59",
        "2026-09-22T00:00:00",
        "2026-09-22T23:59:59.999999",
        "2026-09-23T00:00:00",
        "2026-09-22T12:00:00",
        "2026-09-22T12:00:00",
        "2026-09-22T12:00:00",
    ]
    calls = [
        Call(
            agent_id=second.agent.id
            if index == 2
            else first.agent.id
            if index != 6
            else None,
            campaign_id=campaigns[1].id
            if index == 2
            else campaigns[0].id
            if index not in (3, 6)
            else None,
            client_id=clients[1].id
            if index in (2, 6)
            else clients[0].id
            if index != 3
            else None,
            from_number="+15550000002"
            if index == 2
            else "+15550000001"
            if index != 6
            else None,
            status=CallLifecycleEnum.completed
            if index in (0, 1, 2, 5)
            else CallLifecycleEnum.exhausted
            if index == 4
            else CallLifecycleEnum.blocked
            if index == 6
            else CallLifecycleEnum.pending,
            outcome=CallOutcomeEnum.interested
            if index in (0, 1, 5)
            else CallOutcomeEnum.not_interested
            if index == 2
            else None,
            sentiment=SentimentEnum.negative
            if index == 2
            else SentimentEnum.positive
            if index in (0, 1)
            else None,
            direction=CallDirectionEnum.inbound
            if index == 2
            else CallDirectionEnum.outbound,
            language="en" if index == 2 else "ru" if index not in (3, 6) else None,
            created_at=datetime.fromisoformat(created),
        )
        for index, created in enumerate(dates)
    ]
    session.add_all(calls)
    await session.flush()

    def attempt(
        index,
        seq,
        *,
        content="",
        summary=None,
        recording=None,
        seconds=None,
        messages=None,
    ):
        answered = datetime(2026, 9, 22, 12) if seconds is not None else None
        return CallAttempt(
            call_id=calls[index].id,
            seq=seq,
            status=CallStatusEnum.completed,
            answered_at=answered,
            ended_at=answered + timedelta(seconds=seconds) if answered else None,
            messages=messages
            if messages is not None
            else [{"role": "user", "content": content}],
            summary=summary,
            recording_url=recording,
        )

    session.add_all(
        [
            attempt(0, 1, content="Скидка 100%_VIP C:\\SMS", seconds=17),
            attempt(
                1,
                1,
                content="СКИДКА 100%_VIP",
                summary="Клиент просит скидку",
                recording="https://recordings.test.invalid/one.wav",
                seconds=90,
            ),
            attempt(1, 2, content="скидка 100%_vip завтра", seconds=5),
            attempt(
                2,
                1,
                content="Скидка 100%_VIP",
                summary="Проблема с оплатой",
                recording="",
                seconds=17,
            ),
            attempt(
                4,
                1,
                messages=[
                    {"role": "system", "content": "secret preamble"},
                    {"role": "event", "content": "secret event"},
                    {"role": "user", "content": {"secret": "structured data"}},
                    {"role": "user", "content": "нет ответа"},
                ],
            ),
            attempt(
                5, 1, content="Добрый день", summary="Перезвонить завтра", seconds=50
            ),
            attempt(5, 2, content="", seconds=None),
        ]
    )
    await session.commit()
    return {
        "ids": [call.id for call in calls],
        "agent": first.agent.id,
        "campaign": campaigns[0].id,
        "archived_campaign": campaigns[1].id,
        "client": clients[0].id,
    }


async def listed(client, **params):
    response = await client.get("/v1/calls", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_searches_all_attempts_and_summaries_without_duplicates(client, history):
    result = await listed(client, search="  СКИДКА 100%_vip  ")
    assert result["count"] == 3
    assert {row["id"] for row in result["data"]} == set(history["ids"][:3])
    assert (await listed(client, search="оплатой"))["data"][0]["id"] == history["ids"][
        2
    ]
    assert (await listed(client, search="перезвонить"))["count"] == 1
    assert (await listed(client, search="%_"))["count"] == 3
    assert (await listed(client, search="C:\\SMS"))["count"] == 1
    assert (await listed(client, search="user"))["count"] == 0
    assert (await listed(client, search="secret"))["count"] == 0
    assert (await listed(client, search="   "))["count"] == 7
    page = await listed(client, search="скидка", offset=1, limit=1)
    assert page["count"] == 3 and len(page["data"]) == 1


async def test_inclusive_creation_days_and_legacy_datetime_bounds(client, history):
    result = await listed(client, date_from="2026-09-22", date_to="2026-09-22")
    assert {row["id"] for row in result["data"]} == {
        history["ids"][i] for i in (1, 2, 4, 5, 6)
    }
    assert (await listed(client, date_from="2026-09-23"))["count"] == 1
    assert (await listed(client, date_to="2026-09-21"))["count"] == 1
    assert (await listed(client, date_to="9999-12-31"))["count"] == 7
    old = await listed(
        client,
        created_from="2026-09-22T03:00:00+03:00",
        created_to="2026-09-22T03:00:00+03:00",
    )
    assert old["count"] == 1 and old["data"][0]["id"] == history["ids"][1]


async def test_client_and_caller_substrings_and_exact_language(client, history):
    assert (await listed(client, client_search=" МАРИЯ "))["count"] == 4
    assert (await listed(client, client_search="450000"))["count"] == 2
    assert (await listed(client, client_search="%"))["count"] == 0
    assert (await listed(client, from_search="000002"))["count"] == 1
    assert (await listed(client, language=" RU "))["count"] == 4
    assert (await listed(client, language="r"))["count"] == 0


async def test_recording_matches_any_attempt_and_preserves_unlinked_calls(
    client, history
):
    recorded = await listed(client, has_recording=True)
    assert recorded["count"] == 1 and recorded["data"][0]["id"] == history["ids"][1]
    assert (await listed(client, has_recording=False))["count"] == 6
    all_calls = await listed(client)
    assert all_calls["count"] == 7
    assert any(row["client"] is None for row in all_calls["data"])
    archived = await listed(client, campaign_id=history["archived_campaign"])
    assert archived["count"] == 1 and archived["data"][0]["id"] == history["ids"][2]


async def test_all_filters_combine_before_paging(client, history):
    filters = {
        "search": "скидка",
        "client_search": "мария",
        "from_search": "00001",
        "agent_id": history["agent"],
        "campaign_id": history["campaign"],
        "client_id": history["client"],
        "call_id": history["ids"][1],
        "direction": "outbound",
        "status": "completed",
        "outcome": "interested",
        "sentiment": "positive",
        "language": "ru",
        "has_recording": True,
        "date_from": "2026-09-22",
        "date_to": "2026-09-22",
    }
    result = await listed(client, **filters)
    assert result["count"] == 1 and result["data"][0]["id"] == history["ids"][1]
    empty_page = await listed(client, **filters, offset=1)
    assert empty_page["count"] == 1 and empty_page["data"] == []
    assert (await listed(client, agent_id=99999))["count"] == 0


async def test_date_and_duration_sorting_are_stable_and_null_durations_last(
    client, history
):
    ids = history["ids"]
    order = [ids[i] for i in (0, 1, 4, 5, 6, 2, 3)]
    assert [
        row["id"] for row in (await listed(client, sort="created_at"))["data"]
    ] == order
    assert [
        row["id"] for row in (await listed(client, sort="-created_at"))["data"]
    ] == order[::-1]
    page = await listed(client, sort="created_at", offset=2, limit=2)
    assert page["count"] == 7 and [row["id"] for row in page["data"]] == order[2:4]
    assert [row["id"] for row in (await listed(client, sort="duration"))["data"]] == [
        ids[i] for i in (1, 0, 2, 3, 4, 5, 6)
    ]
    assert [row["id"] for row in (await listed(client, sort="-duration"))["data"]] == [
        ids[i] for i in (2, 0, 1, 6, 5, 4, 3)
    ]
    # Existing clients that omit sort continue to receive descending IDs.
    assert [row["id"] for row in (await listed(client))["data"]] == ids[::-1]


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-09-23", "date_to": "2026-09-22"},
        {"date_from": "bad"},
        {"created_from": "2026-09-23T00:00:00", "created_to": "2026-09-22T00:00:00"},
        {"call_id": 0},
        {"agent_id": -1},
        {"campaign_id": 0},
        {"has_recording": "maybe"},
        {"direction": "wrong"},
        {"status": "wrong"},
        {"search": "x" * 1601},
        {"client_search": "x" * 129},
        {"language": "x" * 33},
    ],
)
async def test_invalid_filters(client, params):
    assert (await client.get("/v1/calls", params=params)).status_code == 422


@pytest.fixture
def role(app):
    original = app.dependency_overrides[_get_role]

    def set_role(value):
        app.dependency_overrides[_get_role] = lambda: value

    yield set_role
    app.dependency_overrides[_get_role] = original


async def exported(client, fmt="csv", **params):
    response = await client.get("/v1/calls/export", params={"format": fmt, **params})
    assert response.status_code == 200, response.text
    return response


def csv_rows(response):
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"sort": "-duration"},
        {"sort": "duration", "status": "completed"},
        {"sort": "created_at", "search": "скидка"},
        {"has_recording": True},
        {"has_recording": False, "direction": "outbound"},
        {"client_search": "мария", "language": "RU"},
        {"from_search": "0002"},
        {"outcome": "interested", "sentiment": "positive"},
        {"date_from": "2026-09-22", "date_to": "2026-09-22", "sort": "-id"},
    ],
)
async def test_export_rows_are_exactly_what_the_list_shows(client, history, params):
    expected = [
        row["id"] for row in (await listed(client, **params, limit=500))["data"]
    ]
    rows = csv_rows(await exported(client, **params))
    assert [int(row["ID"]) for row in rows] == expected


async def test_export_honors_id_filters_including_archived_campaigns(client, history):
    for params in (
        {"agent_id": history["agent"]},
        {"campaign_id": history["archived_campaign"]},
        {"client_id": history["client"]},
        {"call_id": history["ids"][3]},
    ):
        expected = [row["id"] for row in (await listed(client, **params))["data"]]
        assert expected
        rows = csv_rows(await exported(client, **params))
        assert [int(row["ID"]) for row in rows] == expected


async def test_export_reads_names_and_the_latest_attempt(client, history):
    ids = history["ids"]
    rows = {
        int(row["ID"]): row
        for row in csv_rows(await exported(client, tz="Europe/Kyiv"))
    }
    first = rows[ids[0]]
    assert first["Создан"] == "2026-09-22 02:59:59"
    assert first["Кампания"] == "current"
    assert first["Агент"]
    assert first["Клиент"] == "Мария"
    assert first["Телефон клиента"] == "+49123456789"
    assert first["Номер звонящего"] == "+15550000001"
    assert first["Статус"] == "completed"
    assert first["Результат"] == "interested"
    assert first["Направление"] == "outbound"
    assert first["Начало разговора"] == "2026-09-22 15:00:00"
    assert first["Конец разговора"] == "2026-09-22 15:00:17"
    assert first["Длительность, сек"] == "17"
    assert first["Обратный звонок"] == "нет"
    # Two attempts: timing and summary come from the latest one, as on the list.
    assert rows[ids[1]]["Длительность, сек"] == "5"
    assert rows[ids[1]]["Итог разговора"] == ""
    inbound = rows[ids[2]]
    assert inbound["Итог разговора"] == "Проблема с оплатой"
    assert inbound["Кампания"] == "archived"
    assert inbound["Направление"] == "inbound"
    assert inbound["Тональность"] == "negative"
    assert inbound["Результат"] == "not_interested"
    # No attempt, no client, no agent: empty cells, still one row per call.
    assert rows[ids[3]]["Клиент"] == rows[ids[3]]["Начало разговора"] == ""
    assert rows[ids[6]]["Агент"] == rows[ids[6]]["Кампания"] == ""
    assert len(rows) == 7


async def test_export_masks_uuid_for_the_same_roles_as_the_list(client, history, role):
    admin_rows = csv_rows(await exported(client))
    assert all(row["UUID"] for row in admin_rows)
    for value in (SharedRoleEnum.OWNER, CallRoleEnum.STAFF, CallRoleEnum.VIEWER):
        role(value)
        rows = csv_rows(await exported(client))
        assert "UUID" not in rows[0]
        assert [row["ID"] for row in rows] == [row["ID"] for row in admin_rows]
        sheet = openpyxl.load_workbook(
            io.BytesIO((await exported(client, "xlsx")).content)
        ).active
        assert "UUID" not in [cell.value for cell in sheet[1]]
    role(SharedRoleEnum.NONE)
    assert (await client.get("/v1/calls/export")).status_code == 403


async def test_export_xlsx_has_typed_cells(client, history):
    response = await exported(client, "xlsx", sort="-duration")
    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    rows = list(sheet.iter_rows(values_only=True))
    headers, data = rows[0], rows[1:]
    expected = [row["id"] for row in (await listed(client, sort="-duration"))["data"]]
    assert [row[0] for row in data] == expected
    longest = dict(zip(headers, data[0], strict=True))
    assert longest["Длительность, сек"] == 17
    assert longest["Создан"] == datetime(2026, 9, 22, 23, 59, 59)
    assert longest["Итог разговора"] == "Проблема с оплатой"


@pytest.mark.parametrize(
    "params",
    [
        {"format": "pdf"},
        {"tz": "Mars/Base"},
        {"date_from": "2026-09-23", "date_to": "2026-09-22"},
        {"created_from": "2026-09-23T00:00:00", "created_to": "2026-09-22T00:00:00"},
        {"call_id": 0},
        {"has_recording": "maybe"},
        {"direction": "wrong"},
        {"search": "x" * 1601},
    ],
)
async def test_invalid_export_params(client, params):
    assert (await client.get("/v1/calls/export", params=params)).status_code == 422
