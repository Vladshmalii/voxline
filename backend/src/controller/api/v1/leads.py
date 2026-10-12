"""Public "request a demo" endpoint: a landing-page form becomes a Telegram message.

The bot token lives here, on the server, and never in the page: anything a
browser can read, anyone can use to spam the manager's chat. What a stranger on
the internet can do with this route is therefore deliberately small:

* one JSON object in, field lengths capped, control characters stripped;
* a honeypot field a human never fills (bots do): such a request gets the same
  ``202`` as a real one, so the bot learns nothing;
* a per-address rate limit (Redis, with an in-process fallback if Redis is down
  — a lead form that falls over with Redis is worse than a slightly looser limit);
* nothing is stored: the text is forwarded and forgotten.

Answers: 202 accepted, 422 invalid input, 429 too many requests, 502 Telegram
refused or was unreachable, 503 not configured (``LEADS__BOT_TOKEN`` /
``LEADS__CHAT_ID`` unset).
"""

from __future__ import annotations

import re
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from src.core.redis import RedisBase
from src.settings import SETTINGS

router = APIRouter(prefix="/leads", tags=["leads"])

#: Requests one address may make per window.
_LIMIT = 5
_WINDOW_SECONDS = 3600

#: Fallback counters when Redis is unavailable: ``ip -> (window_start, count)``.
_local: dict[str, tuple[float, int]] = {}

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean(value: str) -> str:
    return _CONTROL.sub("", value).strip()


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    contact: str = Field(min_length=3, max_length=200)
    task: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=1000)
    lang: str = Field(default="", max_length=8)
    #: Honeypot: hidden in the page, so only a bot fills it.
    website: str = Field(default="", max_length=200)

    @field_validator("name", "contact", "task", "message", "lang", mode="after")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _clean(value)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _allowed(ip: str) -> bool:
    """Count this request against ``ip``; False once it is over the limit."""
    key = f"leads:rate:{ip}"
    try:
        client = await RedisBase.get_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, _WINDOW_SECONDS)
        return count <= _LIMIT
    except Exception as exc:  # noqa: BLE001 - never let the limiter take the form down
        logger.warning(f"leads rate limit: redis unavailable ({type(exc).__name__})")
    now = time.monotonic()
    started, count = _local.get(ip, (now, 0))
    if now - started > _WINDOW_SECONDS:
        started, count = now, 0
    _local[ip] = (started, count + 1)
    if len(_local) > 10_000:  # bounded: drop the oldest half
        for stale in sorted(_local, key=lambda k: _local[k][0])[:5_000]:
            _local.pop(stale, None)
    return count + 1 <= _LIMIT


def _text(lead: LeadIn) -> str:
    lines = [
        "Нова заявка на демо Voxline",
        f"Ім’я: {lead.name}",
        f"Контакт: {lead.contact}",
    ]
    if lead.task:
        lines.append(f"Задача: {lead.task}")
    if lead.message:
        lines.append(f"Коментар: {lead.message}")
    if lead.lang:
        lines.append(f"Мова сторінки: {lead.lang}")
    return "\n".join(lines)


async def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Deliver ``text`` to ``chat_id``. Raises ``httpx.HTTPError`` on any failure.

    Plain text on purpose (no ``parse_mode``): visitor input must not be able to
    format, link or mention anything.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        response.raise_for_status()


@router.post("", status_code=202)
async def create_lead(lead: LeadIn, request: Request) -> dict[str, bool]:
    if lead.website:
        return {"ok": True}  # a bot filled the honeypot: look accepted, do nothing

    config = SETTINGS.leads
    if config is None:
        raise HTTPException(status_code=503, detail="leads_not_configured")

    if not await _allowed(_client_ip(request)):
        raise HTTPException(status_code=429, detail="too_many_requests")

    try:
        await send_telegram(config.bot_token, config.chat_id, _text(lead))
    except httpx.HTTPError as exc:
        # Never log the exception text: for an HTTP error it carries the URL, and
        # the URL carries the bot token.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error(f"lead not delivered: {type(exc).__name__} status={status}")
        raise HTTPException(status_code=502, detail="delivery_failed") from None
    return {"ok": True}
