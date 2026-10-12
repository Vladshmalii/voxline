"""First-run bootstrap: control database, first superuser, first organization.

    python -m src.bootstrap --email admin@example.com --password '...' [--org-name Acme]

Idempotent: every step is skipped when already done, so it is safe to run on
every ``docker compose up``. Without ``--email`` (or ``BOOTSTRAP_EMAIL``) only
the schema work happens: control migrations plus every organization database.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import select

from src.settings import SETTINGS, logger  # isort: skip - runs Config.init first

from src import sync_db
from src.core.control import service
from src.core.control.models import Organization
from src.core.db.session import SessionMaker
from src.core.redis import RedisBase

DEFAULT_ORG_NAME = "Default"


async def _ensure_superuser_and_org(
    email: str | None, password: str | None, org_name: str
) -> None:
    SessionMaker.init(SETTINGS.db)
    RedisBase.init(SETTINGS.redis)
    try:
        async with SessionMaker.get_control_session()() as session:
            org = (
                await session.execute(
                    select(Organization).order_by(Organization.id).limit(1)
                )
            ).scalar_one_or_none()
            created_org = False
            if org is None:
                org = await service.create_organization(session, org_name)
                created_org = True
                logger.info(f"Created organization {org.name} ({org.uuid})")
            await session.commit()

            if email and password:
                user = await service.get_user_by_email(session, email)
                if user is None:
                    user = await service.create_user(
                        session,
                        email=email,
                        password=password,
                        name="Administrator",
                        is_superuser=True,
                    )
                    logger.info(f"Created superuser {user.email}")
                elif not user.is_superuser:
                    user.is_superuser = True
                    logger.info(f"Promoted {user.email} to superuser")
                await session.commit()
        # The tenant database (created or pre-existing) is brought to head.
        await sync_db.provision_organization(str(org.uuid))
        if created_org:
            logger.info(f"Tenant database ready for {org.uuid}")
    finally:
        await SessionMaker.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a Voxline installation.")
    parser.add_argument("--email", default=os.environ.get("BOOTSTRAP_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("BOOTSTRAP_PASSWORD"))
    parser.add_argument(
        "--org-name", default=os.environ.get("BOOTSTRAP_ORG_NAME") or DEFAULT_ORG_NAME
    )
    args = parser.parse_args()
    if bool(args.email) != bool(args.password):
        parser.error("--email and --password go together")
    if (
        args.password
        and SETTINGS.application_state.is_production
        and args.password.startswith("change-me")
    ):
        parser.error("refusing the placeholder password in production")

    sync_db.run_control_migrations(retries=180)
    asyncio.run(_ensure_superuser_and_org(args.email, args.password, args.org_name))
    # Remaining organizations (a restored control DB, a new image with new migrations).
    sync_db.sync_databases_parallel(sync_db.load_organizations())


if __name__ == "__main__":
    main()
