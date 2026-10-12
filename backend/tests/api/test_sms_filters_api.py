import codecs
import csv
import io
import tempfile
from datetime import datetime

import openpyxl
import pytest
from sqlalchemy import delete

from src.common.enums.engine import MessageStatusEnum
from src.models.agent import VoiceAgent
from src.models.call import Call
from src.models.campaign import Campaign
from src.models.messaging import Message, Messaging
from src.settings import SETTINGS
from tests.support import seed_stack


@pytest.fixture
async def history(session):
    first = await seed_stack(session)
    second = await seed_stack(session)
    first.agent.name = "Анна"
    second.agent.name = "Алекс"
    route = Messaging(name="main", adapter="mamonty")
    other_route = Messaging(name="backup", adapter="mamonty")
    campaign = Campaign(name="September", agent_id=first.agent.id)
    session.add_all([route, other_route, campaign])
    await session.flush()
    calls = [
        Call(agent_id=first.agent.id, campaign_id=campaign.id),
        Call(agent_id=second.agent.id, campaign_id=campaign.id),
        Call(),
    ]
    session.add_all(calls)
    await session.flush()
    specifications = [
        ("2026-09-21T23:59:59", "Скидка 100%_VIP", calls[0].id, route.id, "delivered"),
        ("2026-09-22T00:00:00", "скидка 100%_VIP!", calls[0].id, route.id, "delivered"),
        (
            "2026-09-22T23:59:59.999999",
            "Скидка 100%_VIP завтра",
            calls[1].id,
            other_route.id,
            "sent",
        ),
        ("2026-09-23T00:00:00", "скидка 100XVIP", None, route.id, "delivered"),
        ("2026-09-22T12:00:00", "Напоминаем о встрече", None, route.id, "queued"),
        ("2026-09-22T12:00:00", "Скидка 100%_VIP", calls[2].id, route.id, "failed"),
        ("2026-09-22T12:00:00", "hello WORLD", None, route.id, "sent"),
    ]
    messages = [
        Message(
            messaging_id=route_id,
            call_id=call_id,
            body=body,
            to_number="+49123456789" if index != 2 else "+49123450000",
            sender="VOXLINE" if index != 6 else "Other",
            status=MessageStatusEnum(status),
            created_at=datetime.fromisoformat(created),
        )
        for index, (created, body, call_id, route_id, status) in enumerate(
            specifications
        )
    ]
    session.add_all(messages)
    await session.commit()
    return {
        "ids": [message.id for message in messages],
        "agent": first.agent.id,
        "other_agent": second.agent.id,
        "call": calls[0].id,
        "campaign": campaign.id,
        "route": route.id,
    }


async def listed(client, **params):
    response = await client.get("/v1/sms", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_creation_day_is_inclusive_and_bounds_can_be_open(client, history):
    ids = history["ids"]
    day = await listed(client, date_from="2026-09-22", date_to="2026-09-22")
    assert day["count"] == 5
    assert {row["id"] for row in day["data"]} == {ids[i] for i in (1, 2, 4, 5, 6)}
    assert (await listed(client, date_to="2026-09-21"))["count"] == 1
    assert (await listed(client, date_from="2026-09-23"))["count"] == 1
    assert (await listed(client, date_to="9999-12-31"))["count"] == 7


async def test_creation_time_bounds_are_inclusive_and_normalized_to_utc(
    client, history
):
    result = await listed(
        client,
        created_from="2026-09-22T15:00:00+03:00",
        created_to="2026-09-22T12:00:00Z",
    )
    assert {row["id"] for row in result["data"]} == {
        history["ids"][i] for i in (4, 5, 6)
    }
    assert (await listed(client, created_to="2026-09-22T11:59:59.999999Z"))[
        "count"
    ] == 2
    assert (await listed(client, created_from="2026-09-22T12:00:01"))["count"] == 2
    whole_day = await listed(
        client,
        created_from="2026-09-22T00:00:00Z",
        created_to="2026-09-22T23:59:59.999999Z",
    )
    assert whole_day["count"] == 5
    assert (await listed(client, created_from="2026-09-22T12:00:00Z", search="WORLD"))[
        "count"
    ] == 1


async def test_search_is_case_insensitive_literal_and_trims_spaces(client, history):
    literal = await listed(client, search="  СКИДКА 100%_vip  ")
    assert {row["id"] for row in literal["data"]} == {
        history["ids"][i] for i in (0, 1, 2, 5)
    }
    assert (await listed(client, search="%_"))["count"] == 4
    assert (await listed(client, search="world"))["count"] == 1
    assert (await listed(client, search="   "))["count"] == 7
    assert (await listed(client, search="' OR 1=1 --"))["count"] == 0


async def test_filters_combine_before_count_and_pagination(client, history):
    params = {
        "agent_id": history["agent"],
        "campaign_id": history["campaign"],
        "call_id": history["call"],
        "source": "call",
        "messaging_id": history["route"],
        "status": "delivered",
        "search": "скидка",
        "to_search": "456789",
        "sender": "qod",
        "date_from": "2026-09-22",
        "date_to": "2026-09-22",
    }
    result = await listed(client, **params)
    assert result["count"] == 1
    assert result["data"][0]["id"] == history["ids"][1]
    assert (await listed(client, **params, offset=1))["data"] == []
    assert (await listed(client, **params, offset=1))["count"] == 1
    assert (await listed(client, campaign_id=history["campaign"]))["count"] == 3
    assert (await listed(client, agent_id=9999))["count"] == 0


async def test_number_search_and_legacy_exact_destination(client, history):
    assert (await listed(client, to_search="2345"))["count"] == 7
    assert (await listed(client, to="2345"))["count"] == 0
    assert (await listed(client, to="+49123450000"))["count"] == 1
    assert (await listed(client, to_search="%"))["count"] == 0
    assert (await listed(client, sender="other"))["data"][0]["id"] == history["ids"][6]


async def test_source_and_agent_metadata_keep_unlinked_messages(
    client, session, history
):
    assert (await listed(client, source="manual"))["count"] == 3
    assert (await listed(client, source="call"))["count"] == 4
    result = await listed(client)
    assert result["count"] == 7
    rows = {row["id"]: row for row in result["data"]}
    linked = rows[history["ids"][1]]
    assert linked["agent_name"] == "Анна"
    assert linked["agent_id"] == history["agent"]
    assert linked["call_id"] == history["call"]
    assert (await client.get(f"/v1/sms/{linked['id']}")).json() == linked
    assert rows[history["ids"][4]]["agent_id"] is None
    assert rows[history["ids"][4]]["call_id"] is None
    await session.execute(
        delete(VoiceAgent).where(VoiceAgent.id == history["other_agent"])
    )
    await session.commit()
    deleted = (await client.get(f"/v1/sms/{history['ids'][2]}")).json()
    assert deleted["call_id"] is not None and deleted["agent_name"] is None
    assert (await listed(client))["count"] == 7


async def test_sort_is_by_creation_time_with_stable_ties_and_paging(client, history):
    ids = history["ids"]
    ordered = [ids[i] for i in (0, 1, 4, 5, 6, 2, 3)]
    assert [
        row["id"] for row in (await listed(client, sort="oldest"))["data"]
    ] == ordered
    assert [row["id"] for row in (await listed(client))["data"]] == ordered[::-1]
    page = await listed(client, sort="oldest", offset=2, limit=2)
    assert page["count"] == 7
    assert [row["id"] for row in page["data"]] == ordered[2:4]


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-09-23", "date_to": "2026-09-22"},
        {"date_from": "bad"},
        {
            "created_from": "2026-09-22T12:01:00Z",
            "created_to": "2026-09-22T15:00:00+03:00",
        },
        {"created_from": "bad"},
        {"agent_id": 0},
        {"call_id": -1},
        {"campaign_id": 0},
        {"source": "unknown"},
        {"sort": "unknown"},
        {"search": "x" * 1601},
        {"limit": 501},
        {"offset": -1},
    ],
)
async def test_invalid_list_filters(client, params):
    assert (await client.get("/v1/sms", params=params)).status_code == 422


async def exported(client, fmt="csv", **params):
    response = await client.get("/v1/sms/export", params={"format": fmt, **params})
    assert response.status_code == 200, response.text
    return response


def csv_rows(response):
    assert response.content.startswith(codecs.BOM_UTF8)
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


async def test_export_without_filters_is_the_whole_history_in_list_order(
    client, history
):
    response = await exported(client)
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;") and 'filename="sms_' in disposition
    rows = csv_rows(response)
    listed_ids = [row["id"] for row in (await listed(client))["data"]]
    assert len(rows) == 7
    assert [int(row["ID"]) for row in rows] == listed_ids


@pytest.mark.parametrize(
    "params",
    [
        {"source": "manual"},
        {"sort": "oldest", "search": "скидка"},
        {"status": "delivered", "to_search": "456789"},
        {"created_from": "2026-09-22T15:00:00+03:00", "date_to": "2026-09-22"},
        {"sender": "other"},
        {"search": "nothing matches this"},
    ],
)
async def test_export_rows_are_exactly_what_the_list_shows(client, history, params):
    expected = [
        row["id"] for row in (await listed(client, **params, limit=500))["data"]
    ]
    rows = csv_rows(await exported(client, **params))
    assert [int(row["ID"]) for row in rows] == expected


async def test_export_honors_agent_and_campaign_filters(client, history):
    for params in (
        {"agent_id": history["agent"]},
        {"campaign_id": history["campaign"], "messaging_id": history["route"]},
        {"call_id": history["call"]},
    ):
        expected = [row["id"] for row in (await listed(client, **params))["data"]]
        assert expected
        rows = csv_rows(await exported(client, **params))
        assert [int(row["ID"]) for row in rows] == expected


async def test_export_columns_resolve_names_and_write_times_in_tz(client, history):
    ids = history["ids"]
    utc = {int(row["ID"]): row for row in csv_rows(await exported(client))}
    assert utc[ids[1]]["Создано"] == "2026-09-22 00:00:00"
    kyiv = {
        int(row["ID"]): row
        for row in csv_rows(await exported(client, tz="Europe/Kyiv"))
    }
    linked = kyiv[ids[1]]
    assert linked["Создано"] == "2026-09-22 03:00:00"
    assert linked["Агент"] == "Анна"
    assert linked["Кампания"] == "September"
    assert linked["Маршрут"] == "main"
    assert linked["Источник"] == "call"
    assert linked["ID звонка"] == str(history["call"])
    assert linked["Статус"] == "delivered"
    assert linked["Получатель"] == "+49123456789"
    assert linked["Текст"] == "скидка 100%_VIP!"
    manual = kyiv[ids[4]]
    assert manual["Источник"] == "manual"
    assert manual["Агент"] == manual["Кампания"] == manual["ID звонка"] == ""
    assert kyiv[ids[2]]["Маршрут"] == "backup"


async def test_export_never_turns_text_into_formulas(client, session, history):
    session.add(
        Message(
            messaging_id=history["route"],
            body='=HYPERLINK("https://evil.test.invalid","x")',
            to_number="+49123456789",
            sender="@VOXLINE",
            created_at=datetime(2026, 9, 24),
        )
    )
    await session.commit()
    (row,) = csv_rows(await exported(client, search="HYPERLINK"))
    assert row["Текст"] == """'=HYPERLINK("https://evil.test.invalid","x")"""
    assert row["Отправитель"] == "'@VOXLINE"
    assert row["Получатель"] == "+49123456789"

    response = await exported(client, "xlsx", search="HYPERLINK")
    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    headers = [cell.value for cell in sheet[1]]
    body = sheet.cell(row=2, column=headers.index("Текст") + 1)
    assert body.data_type == "s"
    assert body.value == '=HYPERLINK("https://evil.test.invalid","x")'


async def test_export_xlsx_has_typed_cells_in_list_order(client, history):
    response = await exported(client, "xlsx", sort="oldest", tz="Europe/Kyiv")
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'filename="sms_' in response.headers["content-disposition"]
    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    rows = list(sheet.iter_rows(values_only=True))
    headers, data = rows[0], rows[1:]
    assert headers[:3] == ("ID", "Создано", "Отправлено")
    expected = [row["id"] for row in (await listed(client, sort="oldest"))["data"]]
    assert [row[0] for row in data] == expected
    first = dict(zip(headers, data[0], strict=True))
    assert first["Создано"] == datetime(2026, 9, 22, 2, 59, 59)
    assert first["Сегменты"] == 1
    assert first["Агент"] == "Анна"
    assert first["Отправлено"] is None


async def test_export_refuses_more_rows_than_allowed_and_leaves_no_file(
    client, history, monkeypatch, tmp_path
):
    monkeypatch.setattr(SETTINGS, "export_max_rows", 2)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for fmt in ("csv", "xlsx"):
        response = await client.get("/v1/sms/export", params={"format": fmt})
        assert response.status_code == 422
        assert "narrow the filters" in response.json()["detail"]
        assert list(tmp_path.iterdir()) == []
        rows = await exported(client, fmt, source="call", status="delivered")
        assert rows.content
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "params",
    [
        {"format": "pdf"},
        {"tz": "Mars/Base"},
        {"tz": "../../etc/passwd"},
        {"date_from": "2026-09-23", "date_to": "2026-09-22"},
        {
            "created_from": "2026-09-22T12:01:00Z",
            "created_to": "2026-09-22T15:00:00+03:00",
        },
        {"agent_id": 0},
        {"source": "unknown"},
        {"sort": "unknown"},
        {"search": "x" * 1601},
    ],
)
async def test_invalid_export_params(client, params):
    assert (await client.get("/v1/sms/export", params=params)).status_code == 422


async def test_export_filename_is_readable_from_a_cross_origin_admin(client, history):
    response = await client.get(
        "/v1/sms/export", headers={"Origin": "https://admin.test.invalid"}
    )
    assert response.status_code == 200
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "content-disposition" in exposed.lower()
