"""Schema management: the control database and every organization database.

``python -m src.sync_db`` (the ``migrate`` step of a deploy):

1. creates the control database if it is missing and upgrades it to head
   (``src/infrastructure/control_migrations``);
2. reads the active organizations from it;
3. creates each organization database ``{DB__PREFIX}{uuid}`` if missing and
   upgrades it to head (``src/infrastructure/db/migrations``), in parallel.

``provision_organization`` is the same tenant step for a single organization,
used when the admin API or the bootstrap CLI creates one.
"""

import asyncio
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import psycopg2
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from psycopg2 import errors, sql

from src.settings import SETTINGS, logger

_ROOT = pathlib.Path(__file__).parent.parent
ALEMBIC_INI = str(_ROOT / "alembic.ini")
ALEMBIC_CONTROL_INI = str(_ROOT / "alembic_control.ini")


def _admin_connection(retries: int = 1):
    """Autocommit connection to the ``postgres`` maintenance database."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(
                dbname="postgres",
                user=SETTINGS.db.user,
                password=SETTINGS.db.password,
                host=SETTINGS.db.host,
                port=SETTINGS.db.port,
            )
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as e:
            last = e
            if attempt + 1 < retries:
                logger.warning(f"Postgres not reachable yet ({e}); retrying")
                time.sleep(1)
    raise last  # type: ignore[misc]


def ensure_databases(db_names: set[str], retries: int = 1) -> None:
    """Create whichever of ``db_names`` do not exist yet."""
    if not db_names:
        return
    conn = _admin_connection(retries)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database WHERE datname = ANY(%s)",
                (list(db_names),),
            )
            exists = {el[0] for el in cur.fetchall()}
            for db_name in db_names - exists:
                try:
                    cur.execute(
                        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name))
                    )
                    logger.info(f"Created database {db_name}")
                except errors.DuplicateDatabase:
                    logger.debug(f"Database {db_name} already created concurrently")
    finally:
        conn.close()


def check_dbs(org_uuids) -> None:
    """Create the organization databases that are missing."""
    ensure_databases({f"{SETTINGS.db.prefix}{org_uuid}" for org_uuid in org_uuids})


def drop_organization_database(org_uuid: str) -> None:
    conn = _admin_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(f"{SETTINGS.db.prefix}{org_uuid}")
                )
            )
    finally:
        conn.close()


# -- control database -----------------------------------------------------------


def control_alembic_config() -> Config:
    cfg = Config(ALEMBIC_CONTROL_INI)
    cfg.set_main_option(
        "sqlalchemy.url", f"{SETTINGS.db.url}/{SETTINGS.db.control_name}"
    )
    return cfg


def run_control_migrations(retries: int = 1) -> None:
    """Create the control database if needed and upgrade it to head."""
    ensure_databases({SETTINGS.db.control_name}, retries=retries)
    logger.debug("Migrating control database")
    try:
        command.upgrade(control_alembic_config(), "head")
    except CommandError as e:
        logger.error(f"Failed to run control upgrade: {e}")
        raise


def load_organizations(retries=180) -> list[str]:
    """UUIDs of the active organizations, read from the control database."""
    for _ in range(retries):
        try:
            conn = psycopg2.connect(
                dbname=SETTINGS.db.control_name,
                user=SETTINGS.db.user,
                password=SETTINGS.db.password,
                host=SETTINGS.db.host,
                port=SETTINGS.db.port,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT uuid FROM organizations WHERE is_active ORDER BY id"
                    )
                    return [str(row[0]) for row in cur.fetchall()]
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 - retry loop, any failure should retry
            logger.error(f"Failed to get organizations: {e}. Retrying...")
            time.sleep(1)
    logger.error("Failed to get organizations from the control database")
    sys.exit(1)


# -- organization databases -----------------------------------------------------


def sync_databases_parallel(list_of_organizations: list[str], max_workers=10):
    if not list_of_organizations:
        logger.warning("No organizations found")
        return

    check_dbs(list_of_organizations)

    logger.debug(f"Syncing {len(list_of_organizations)} organizations")

    any_failed = False
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_migrations, org): org for org in list_of_organizations
        }
        for future in as_completed(futures):
            org = futures[future]
            try:
                future.result()
                logger.info(f"Migration completed for {org}")
            except Exception as e:  # noqa: BLE001 - one org failure must not stop the rest
                logger.exception(f"Migration failed for {org}: {e}")
                any_failed = True
    if any_failed:
        sys.exit(1)


async def run_migrations_async(organization: str):
    await asyncio.to_thread(run_migrations, organization)


async def provision_organization(organization: str) -> None:
    """Create ``{prefix}{organization}`` and run the tenant migrations on it.

    Blocking psycopg2/alembic work runs in a thread (the alembic env starts its
    own event loop, which needs a thread with none running).
    """
    await asyncio.to_thread(ensure_databases, {f"{SETTINGS.db.prefix}{organization}"})
    await run_migrations_async(organization)


def run_migrations(organization: str):
    logger.debug(f"Migrating {organization}")
    alembic_cfg = Config(ALEMBIC_INI)
    alembic_cfg.set_main_option(
        "sqlalchemy.url", f"{SETTINGS.db.url}/{SETTINGS.db.prefix}{organization}"
    )

    try:
        command.upgrade(alembic_cfg, "head")
    except CommandError as e:
        logger.error(f"Failed to run upgrade: {e}")
        raise


def generate_revision(with_organization: str):
    alembic_cfg = Config(ALEMBIC_INI)
    alembic_cfg.set_main_option(
        "sqlalchemy.url", f"{SETTINGS.db.url}/{SETTINGS.db.prefix}{with_organization}"
    )
    command.revision(alembic_cfg, autogenerate=True)


def generate_control_revision(message: str):
    command.revision(control_alembic_config(), message=message, autogenerate=True)


def main():
    run_control_migrations(retries=180)
    sync_databases_parallel(load_organizations())


if __name__ == "__main__":
    main()
