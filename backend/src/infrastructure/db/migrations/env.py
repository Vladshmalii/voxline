import asyncio
from alembic import context, autogenerate
from alembic.operations import ops
from logging.config import fileConfig
from sqlalchemy import pool, text, TypeDecorator
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

def render_item(type_, obj, autogen_context):
    """Apply custom rendering for selected items."""

    if type_ == 'type' and isinstance(obj, TypeDecorator):
        return f"sa.{obj.impl!r}"

    # default rendering for other objects
    return False

from src.settings import SETTINGS
from src.models import Base

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support

target_metadata = Base.metadata


writer = autogenerate.rewriter.Rewriter()

@writer.rewrites(ops.MigrationScript)
def add_imports(context, revision, op):
    op.imports.add("import src.core.db.models")
    return [op]

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SETTINGS.service_prefix,
        include_schemas=True,
        render_item=render_item,
        process_revision_directives=writer,

    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # The per-tenant database is created by ``sync_db.check_dbs`` but the
    # service schema is not — ensure it exists before the version table or any
    # table is created inside it.
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SETTINGS.service_prefix}"'))
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        process_revision_directives=writer,
        include_schemas=True,
        version_table_schema=SETTINGS.service_prefix,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
