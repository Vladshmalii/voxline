import psycopg2
from alembic import command
from alembic.config import Config

from src.settings import SETTINGS
from src.sync_db import ALEMBIC_INI
from tests import support


def test_split_balance_migration_preserves_funds_and_classifies_history():
    org = support.new_org_uuid()
    support.create_org_database(org)
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option(
        "sqlalchemy.url", f"{SETTINGS.db.url}/{SETTINGS.db.prefix}{org}"
    )

    def connect():
        return psycopg2.connect(
            dbname=f"{SETTINGS.db.prefix}{org}",
            host=SETTINGS.db.host,
            port=SETTINGS.db.port,
            user=SETTINGS.db.user,
            password=SETTINGS.db.password,
        )

    try:
        command.downgrade(cfg, "ea92c5d78b10")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO call.organizationbalance (balance) VALUES (123.45)"
            )
            cur.execute("""INSERT INTO call.balancetransaction (uuid, amount, type, description, balance_after)
                VALUES ('00000000-0000-0000-0000-000000000001', 123.45, 'deposit', 'old deposit', 123.45),
                       ('00000000-0000-0000-0000-000000000002', -2, 'sms_usage', 'old SMS', 121.45),
                       ('00000000-0000-0000-0000-000000000003', -3, 'call_usage', 'old call', 118.45)""")
        command.upgrade(cfg, "head")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT call_balance, sms_balance FROM call.organizationbalance"
            )
            assert cur.fetchone() == (123.45, 0)
            cur.execute("SELECT type, channel FROM call.balancetransaction ORDER BY id")
            assert cur.fetchall() == [
                ("deposit", "calls"),
                ("sms_usage", "sms"),
                ("call_usage", "calls"),
            ]
            cur.execute(
                "SELECT balance_after, legacy_balance_after FROM call.balancetransaction WHERE channel = 'sms'"
            )
            assert cur.fetchone() == (None, 121.45)
            cur.execute("UPDATE call.organizationbalance SET sms_balance = 10")
        command.downgrade(cfg, "ea92c5d78b10")
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT balance FROM call.organizationbalance")
            assert cur.fetchone() == (133.45,)
            cur.execute(
                "SELECT balance_after FROM call.balancetransaction WHERE type = 'sms_usage'"
            )
            assert cur.fetchone() == (121.45,)
        command.upgrade(cfg, "head")
    finally:
        support.drop_org_database(org)
