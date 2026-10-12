"""Shared bootstrap for the DB-backed suites (tests/api, tests/worker).

Import order is the whole trick: environment first, ``src`` second — importing
``src.settings`` freezes ``Settings()`` and runs the core ``Config.init``,
so everything here happens at module import, before any test file pulls in
application code.

The suites run against the local dev containers (postgres:17 and redis on
127.0.0.1, overridable via ``TEST_DB_*``/``TEST_REDIS_*``); when either is
absent the suites skip rather than fail — same spirit as the engine suite's
pipecat guard. Each pytest session gets a fresh ``org_<random>`` database
migrated by the *real* ``sync_db.run_migrations``, so every run re-proves the
alembic migration on an empty database.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent

# Baseline from the example env, then pin the pieces tests own. Explicit
# assignment (not setdefault): a shell that happens to export DB__HOST must
# not silently point the suite at a real database.
load_dotenv(_ROOT / ".env.example")
os.environ.update(
    {
        "SERVICE_PREFIX": "call",
        # A scratch control database per run; the auth suite creates it.
        "DB__CONTROL_NAME": f"voxline_ctl_test_{uuid.uuid4().hex[:8]}",
        "JWT__SECRET": "test-jwt-secret-not-for-production",
        "JWT__COOKIE_SECURE": "false",
        "DB__HOST": os.environ.get("TEST_DB_HOST", "127.0.0.1"),
        "DB__PORT": os.environ.get("TEST_DB_PORT", "5432"),
        "DB__USER": os.environ.get("TEST_DB_USER", "postgres"),
        "DB__PASSWORD": os.environ.get("TEST_DB_PASSWORD", "postgres"),
        "REDIS__TYPE": "standalone",
        "REDIS__HOST": os.environ.get("TEST_REDIS_HOST", "127.0.0.1"),
        "REDIS__PORT": os.environ.get("TEST_REDIS_PORT", "6379"),
        "REDIS__PASSWORD": os.environ.get("TEST_REDIS_PASSWORD", "redis"),
        "CALL_WORKER__MEDIA_URL": "wss://media.test.invalid/api/v1",
        "CALL_WORKER__DIAL_TIMEOUT_SECONDS": "60",
    }
)

import psycopg2
import redis as redis_sync
from psycopg2 import sql

from src.settings import SETTINGS


def postgres_unavailable() -> str | None:
    """Why a Postgres-only suite cannot run here, or None if it can."""
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            host=SETTINGS.db.host,
            port=SETTINGS.db.port,
            user=SETTINGS.db.user,
            password=SETTINGS.db.password,
            connect_timeout=2,
        )
        conn.close()
    except Exception as exc:  # noqa: BLE001
        return f"postgres unavailable at {SETTINGS.db.host}:{SETTINGS.db.port}: {exc}"
    return None


def services_unavailable() -> str | None:
    """Why the DB-backed suites cannot run here, or None if they can."""
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            host=SETTINGS.db.host,
            port=SETTINGS.db.port,
            user=SETTINGS.db.user,
            password=SETTINGS.db.password,
            connect_timeout=2,
        )
        conn.close()
    except Exception as exc:  # noqa: BLE001
        return f"postgres unavailable at {SETTINGS.db.host}:{SETTINGS.db.port}: {exc}"
    try:
        client = redis_sync.Redis(
            host=SETTINGS.redis.host,
            port=SETTINGS.redis.port,
            password=SETTINGS.redis.password,
            socket_connect_timeout=2,
        )
        client.ping()
        client.close()
    except Exception as exc:  # noqa: BLE001
        return (
            f"redis unavailable at {SETTINGS.redis.host}:{SETTINGS.redis.port}: {exc}"
        )
    return None


def create_org_database(org_uuid: str) -> None:
    """Create the org database and run the real migrations against it."""
    conn = psycopg2.connect(
        dbname="postgres",
        host=SETTINGS.db.host,
        port=SETTINGS.db.port,
        user=SETTINGS.db.user,
        password=SETTINGS.db.password,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(f"{SETTINGS.db.prefix}{org_uuid}")
            )
        )
    conn.close()

    from src.sync_db import run_migrations

    run_migrations(org_uuid)


def drop_org_database(org_uuid: str) -> None:
    conn = psycopg2.connect(
        dbname="postgres",
        host=SETTINGS.db.host,
        port=SETTINGS.db.port,
        user=SETTINGS.db.user,
        password=SETTINGS.db.password,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(f"{SETTINGS.db.prefix}{org_uuid}")
            )
        )
    conn.close()


def drop_database(name: str) -> None:
    conn = psycopg2.connect(
        dbname="postgres",
        host=SETTINGS.db.host,
        port=SETTINGS.db.port,
        user=SETTINGS.db.user,
        password=SETTINGS.db.password,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
    conn.close()


def database_exists(name: str) -> bool:
    conn = psycopg2.connect(
        dbname="postgres",
        host=SETTINGS.db.host,
        port=SETTINGS.db.port,
        user=SETTINGS.db.user,
        password=SETTINGS.db.password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def create_control_database() -> None:
    """Create the scratch control database and run the real control migrations."""
    from src.sync_db import run_control_migrations

    run_control_migrations()


def drop_control_database() -> None:
    drop_database(SETTINGS.db.control_name)


def new_org_uuid() -> str:
    return f"test{uuid.uuid4().hex[:10]}"


#: The suites enqueue real taskiq messages into the shared local redis —
#: where a developer's `docker compose up` stack may have a live worker
#: reading the production stream. A unique per-run stream name keeps the two
#: worlds apart; conftests point the broker at it. One module-level suffix, so
#: a second conftest calling ``isolate_broker`` renames to the *same* name
#: instead of pulling the stream out from under an already-started broker.
_QUEUE_SUFFIX = f"test_{uuid.uuid4().hex[:8]}"


def isolate_broker() -> None:
    from src.application.worker import tasks

    # Computed from SETTINGS, not from the broker's current queue_name: a
    # second conftest calling this in the same session must land on the exact
    # same name, not append the suffix twice.
    tasks.broker.queue_name = f"{SETTINGS.service_prefix}_taskiq_{_QUEUE_SUFFIX}"


async def start_broker() -> None:
    """Start the broker the way the taskiq CLI does in the worker process.

    The Redis broker kicked lazily; the Postgres one refuses to ``kick()``
    before ``startup()``. Producers cover themselves (``enqueue_dial``), but a
    test calling ``sweep_calls`` directly is acting as the worker process, and
    the worker's startup is the CLI's job — so here it is the suite's.
    Idempotent via the same flag ``enqueue_dial`` checks, so whichever side
    starts first wins and the other becomes a no-op.
    """
    from src.application.worker import tasks

    if not getattr(tasks.broker, "_voxline_started", False):
        await tasks.broker.startup()
        tasks.broker._voxline_started = True


async def queue_depth() -> int:
    """Messages currently in the isolated stream (0 if never kicked)."""
    from redis.asyncio import Redis

    from src.application.worker import tasks

    broker = tasks.broker
    async with Redis(connection_pool=broker.connection_pool) as redis_conn:
        return await redis_conn.xlen(broker.queue_name)


async def purge_queue() -> None:
    """Empty the isolated stream between tests.

    Trims entries rather than deleting the stream key outright: deleting it
    would also drop the consumer group ``startup()`` declared on it, and the
    next ``listen()`` would fail with NOGROUP instead of just seeing an empty
    queue.
    """
    from redis.asyncio import Redis

    from src.application.worker import tasks

    broker = tasks.broker
    async with Redis(connection_pool=broker.connection_pool) as redis_conn:
        await redis_conn.xtrim(broker.queue_name, maxlen=0)


async def shutdown_broker() -> None:
    """Close the broker's connection pool, if it ever started.

    Idempotent: both suites' session fixtures call this at session end.
    ``RedisStreamBroker.shutdown`` disconnects its own pool, so a second call
    is a no-op against an already-disconnected pool rather than an error.
    """
    from src.application.worker import tasks

    broker = tasks.broker
    await broker.shutdown()
    broker._voxline_started = False


# ---------------------------------------------------------------------------
# Seeding: the minimal complete stack an agent needs, built through the CRUDs.
# ---------------------------------------------------------------------------


async def seed_stack(
    session,
    *,
    agent_active: bool = True,
    telephony_active: bool = True,
    with_telephony: bool = True,
    media_url_base: str | None = None,
):
    """Provider + three models + telephony + one agent, ready to dial.

    Returns an object with ``provider``, ``stt``/``tts``/``ttt``, ``telephony``
    (may be None) and ``agent`` attributes.
    """
    from types import SimpleNamespace

    from src.common.enums.engine import ProviderKindEnum
    from src.repositories.agent import VoiceAgentCRUD
    from src.repositories.provider import ModelCRUD, ModelProviderCRUD
    from src.repositories.telephony import TelephonyCRUD

    provider = await ModelProviderCRUD(session).create(
        {"name": "gpu-1", "url": "ws://127.0.0.1:59101/v1/realtime", "api_key": "k"}
    )
    models = {}
    for kind, adapter, code in (
        (ProviderKindEnum.stt, "qwen3_asr", "Qwen/Qwen3-ASR-1.7B"),
        (ProviderKindEnum.tts, "qwen3_tts", "qwen3-tts"),
        (ProviderKindEnum.ttt, "openai_compatible", "llm-32b"),
    ):
        models[kind] = await ModelCRUD(session).create(
            {
                "name": f"{kind}-model",
                "kind": kind,
                "adapter": adapter,
                "code": code,
                "is_active": True,
                "provider_id": provider.id,
            }
        )

    telephony = None
    if with_telephony:
        options = {"media_url_base": media_url_base} if media_url_base else {}
        telephony = await TelephonyCRUD(session).create(
            {
                "name": "trunk",
                "adapter": "sip_bridge",
                "is_active": telephony_active,
                "caller_id": "+15550000001",
                "control_url": "http://127.0.0.1:59109/bridge",
                "options": options,
            }
        )

    agent = await VoiceAgentCRUD(session).create(
        {
            "name": "support",
            "is_active": agent_active,
            "system_prompt": "You are a voice agent.",
            "spoken_silence": "Are you there?",
            "spoken_reprompt": "Go on?",
            "spoken_goodbye": "Bye.",
            "tts_voice": "vivian",
            "stt_model_id": models[ProviderKindEnum.stt].id,
            "tts_model_id": models[ProviderKindEnum.tts].id,
            "ttt_model_id": models[ProviderKindEnum.ttt].id,
            "telephony_id": telephony.id if telephony else None,
        }
    )
    return SimpleNamespace(
        provider=provider,
        stt=models[ProviderKindEnum.stt],
        tts=models[ProviderKindEnum.tts],
        ttt=models[ProviderKindEnum.ttt],
        telephony=telephony,
        agent=agent,
    )


async def fund(session, *, calls: float = 1000.0, sms: float = 1000.0) -> None:
    """Give the organization a balance to spend.

    Dialing and texting are gated on funds, and a fresh organization has none;
    tests that exercise those paths top it up first.
    """
    from sqlalchemy import select

    from src.models.billing import OrganizationBalance

    balance = (
        await session.execute(select(OrganizationBalance).limit(1))
    ).scalar_one_or_none()
    if balance is None:
        session.add(OrganizationBalance(call_balance=calls, sms_balance=sms))
    else:
        balance.call_balance, balance.sms_balance = calls, sms
    await session.commit()
