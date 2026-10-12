"""The public demo-request endpoint: what a stranger can and cannot make it do."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests import support  # noqa: F401  (pins the environment before src imports)

from src.controller.api.v1 import leads
from src.settings import SETTINGS, LeadsSettings

GOOD = {"name": "Олена", "contact": "+380671112233", "task": "Підтвердження замовлень"}


@pytest.fixture
def client(monkeypatch):
    sent: list[tuple[str, str, str]] = []

    async def fake_send(token: str, chat_id: str, text: str) -> None:
        sent.append((token, chat_id, text))

    async def no_redis():
        raise ConnectionError("no redis in this test")

    monkeypatch.setattr(leads, "send_telegram", fake_send)
    monkeypatch.setattr(leads.RedisBase, "get_client", no_redis)  # exercise the fallback limiter
    monkeypatch.setattr(SETTINGS, "leads", LeadsSettings(bot_token="T", chat_id="42"))
    leads._local.clear()

    app = FastAPI()
    app.include_router(leads.router)
    test_client = TestClient(app)
    test_client.sent = sent
    return test_client


def test_a_request_is_forwarded_as_plain_text(client):
    response = client.post("/leads", json={**GOOD, "message": "Хочу демо", "lang": "uk"})

    assert response.status_code == 202 and response.json() == {"ok": True}
    token, chat_id, text = client.sent[0]
    assert (token, chat_id) == ("T", "42")
    assert "Олена" in text and "+380671112233" in text and "Хочу демо" in text


def test_a_filled_honeypot_looks_accepted_but_sends_nothing(client):
    response = client.post("/leads", json={**GOOD, "website": "http://spam.example"})

    assert response.status_code == 202
    assert client.sent == []


@pytest.mark.parametrize(
    "payload",
    [
        {"contact": "+380671112233"},  # no name
        {"name": "x", "contact": "1"},  # contact too short
        {**GOOD, "name": "x" * 101},
        {**GOOD, "message": "x" * 1001},
    ],
)
def test_bad_input_is_refused(client, payload):
    assert client.post("/leads", json=payload).status_code == 422
    assert client.sent == []


def test_control_characters_are_stripped(client):
    client.post("/leads", json={**GOOD, "name": "Ol\x00en\x07a"})

    assert "Olena" in client.sent[0][2]


def test_one_address_is_rate_limited(client):
    codes = [client.post("/leads", json=GOOD).status_code for _ in range(leads._LIMIT + 2)]

    assert codes[: leads._LIMIT] == [202] * leads._LIMIT
    assert codes[leads._LIMIT :] == [429, 429]


def test_unconfigured_answers_503(client, monkeypatch):
    monkeypatch.setattr(SETTINGS, "leads", None)

    assert client.post("/leads", json=GOOD).status_code == 503


def test_a_telegram_failure_is_a_502_that_never_leaks_the_token(client, monkeypatch, caplog):
    import httpx

    async def boom(token: str, chat_id: str, text: str) -> None:
        raise httpx.ConnectError("https://api.telegram.org/botSECRET-TOKEN/sendMessage")

    monkeypatch.setattr(leads, "send_telegram", boom)
    response = client.post("/leads", json=GOOD)

    assert response.status_code == 502
    assert "SECRET-TOKEN" not in response.text
