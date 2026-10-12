"""Admin Account Statistics router: unified analytics for the organization."""

from fastapi import APIRouter

from src.application.services.admin_stats import AdminStatsService
from src.controller.dependencies.db import OrgUuidDep, SessionUserDep
from src.controller.dependencies.permission import admin_only
from src.schemas.admin_stats import SAdminAccountStatsRead

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[admin_only])


@router.get("/stats", response_model=SAdminAccountStatsRead)
async def get_admin_account_stats(
    session: SessionUserDep,
    org_uuid: OrgUuidDep,
):
    """Returns comprehensive analytics for the current company/organization account."""
    return await AdminStatsService(session, org_uuid=org_uuid).get_account_stats()
