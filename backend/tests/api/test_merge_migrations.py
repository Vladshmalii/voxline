"""Upgrade real historical schemas from either side of the merge."""

import re
import shutil

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from src.models.agent import VoiceAgent
from src.models.provider import Model, ModelProvider
from src.settings import SETTINGS
from src.sync_db import ALEMBIC_INI
from tests import support


def migration_config(org):
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "sqlalchemy.url", f"{SETTINGS.db.url}/{SETTINGS.db.prefix}{org}"
    )
    return cfg


def historical_config(cfg, directory, *, moderated):
    """Reproduce each parent's published graph, before their heads were joined."""
    scripts = ScriptDirectory.from_config(cfg)
    shutil.copytree(scripts.dir, directory)
    versions = directory / "versions"
    branch_head = "5b9e1c3a7d42" if moderated else "6dcb902f4a31"
    ancestors = {
        revision.revision for revision in scripts.walk_revisions(head=branch_head)
    }
    if moderated:
        removed = {"f7a2b8c14d90"}
        parent = "39f223faae3b"
    else:
        removed = {"39f223faae3b"}
        parent = "f7a2b8c14d90"
    for path in versions.glob("*_*.py"):
        revision = path.name.split("_", 1)[0]
        if revision not in ancestors or revision in removed:
            path.unlink()
    defaults = next(versions.glob("ea92c5d78b10_*.py"))
    defaults.write_text(
        re.sub(
            r"^down_revision = .*$",
            f"down_revision = {parent!r}",
            defaults.read_text(),
            flags=re.MULTILINE,
        )
    )
    old_cfg = Config(ALEMBIC_INI)
    old_cfg.set_main_option("script_location", str(directory))
    old_cfg.set_main_option("sqlalchemy.url", cfg.get_main_option("sqlalchemy.url"))
    return old_cfg


def seed_agent(cfg):
    engine = create_engine(
        cfg.get_main_option("sqlalchemy.url").replace("+asyncpg", "+psycopg2")
    )
    try:
        with engine.begin() as conn:
            provider = conn.scalar(
                ModelProvider.__table__.insert()
                .values(name="migration", url="http://test.invalid")
                .returning(ModelProvider.id)
            )
            model_ids = []
            for kind, adapter in [
                ("stt", "qwen3_asr"),
                ("tts", "qwen3_tts"),
                ("ttt", "openai_compatible"),
            ]:
                model_ids.append(
                    conn.scalar(
                        Model.__table__.insert()
                        .values(
                            name=kind,
                            kind=kind,
                            adapter=adapter,
                            code="test",
                            provider_id=provider,
                        )
                        .returning(Model.id)
                    )
                )
            return conn.scalar(
                VoiceAgent.__table__.insert()
                .values(
                    name="migration",
                    system_prompt="Test",
                    spoken_silence="Hello?",
                    spoken_reprompt="Repeat?",
                    spoken_goodbye="Bye",
                    tts_voice="test",
                    stt_model_id=model_ids[0],
                    tts_model_id=model_ids[1],
                    ttt_model_id=model_ids[2],
                )
                .returning(VoiceAgent.id)
            )
    finally:
        engine.dispose()


def test_published_sms_revisions_join_one_head():
    scripts = ScriptDirectory.from_config(Config(ALEMBIC_INI))
    assert len(scripts.get_heads()) == 1
    ancestors = {revision.revision for revision in scripts.walk_revisions()}
    assert {
        "f7a2b8c14d90",
        "39f223faae3b",
        "6dcb902f4a31",
        "5b9e1c3a7d42",
        "f4f4ad164ece",
    } <= ancestors


@pytest.mark.parametrize(
    "revision", ["f7a2b8c14d90", "ea92c5d78b10", "6dcb902f4a31", "5b9e1c3a7d42"]
)
def test_merge_upgrade_preserves_sms_text_and_balances(tmp_path, revision):
    org = support.new_org_uuid()
    support.create_org_database(org)
    cfg = migration_config(org)
    moderated = revision == "5b9e1c3a7d42"
    split = revision == "6dcb902f4a31"

    def connect():
        return psycopg2.connect(
            dbname=f"{SETTINGS.db.prefix}{org}",
            host=SETTINGS.db.host,
            port=SETTINGS.db.port,
            user=SETTINGS.db.user,
            password=SETTINGS.db.password,
        )

    try:
        agent_id = seed_agent(cfg)
        command.downgrade(cfg, "c8d3f6a9e152")
        old_cfg = historical_config(
            cfg, tmp_path / "old-migrations", moderated=moderated
        )
        command.upgrade(old_cfg, revision)
        text = "Ваше сообщение: 100%_VIP"
        with connect() as conn, conn.cursor() as cur:
            if moderated:
                cur.execute(
                    "UPDATE call.voiceagent SET sms_tool_enabled = true, sms_tool_message = %s, sms_tool_message_status = 'pending' WHERE id = %s",
                    (text, agent_id),
                )
            else:
                cur.execute(
                    "UPDATE call.voiceagent SET sms_tool_enabled = true, sms_tool_text = %s WHERE id = %s",
                    (text, agent_id),
                )
            if split:
                cur.execute(
                    "INSERT INTO call.organizationbalance (call_balance, sms_balance) VALUES (123.45, 7)"
                )
            else:
                cur.execute(
                    "INSERT INTO call.organizationbalance (balance) VALUES (123.45)"
                )
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT sms_tool_message, sms_tool_message_status, sms_tool_enabled FROM call.voiceagent WHERE id = %s",
                (agent_id,),
            )
            assert cur.fetchone() == (
                text,
                "pending" if moderated else "approved",
                True,
            )
            cur.execute(
                "SELECT call_balance, sms_balance FROM call.organizationbalance"
            )
            assert cur.fetchone() == (123.45, 7 if split else 0)
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'call' AND table_name = 'voiceagent' AND column_name IN ('sms_tool_text', 'sms_tool_prompt')"
            )
            assert cur.fetchall() == []
            cur.execute("SELECT version_num FROM call.alembic_version")
            assert cur.fetchall() == [
                (ScriptDirectory.from_config(cfg).get_current_head(),)
            ]
        # A later downgrade must tolerate the repair having removed legacy text.
        command.downgrade(cfg, "c8d3f6a9e152")
        command.upgrade(cfg, "head")
    finally:
        support.drop_org_database(org)
