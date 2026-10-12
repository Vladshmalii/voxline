"""Billing and finance API router."""


from fastapi import APIRouter, Depends, Query

from src.application.services.billing import BillingService
from src.controller.dependencies.db import SessionUserCommitDep, SessionUserDep
from src.controller.dependencies.permission import (
    FullAccessDep,
    admin_only,
    view_billing,
    write_billing,
)
from src.core.exceptions import Forbidden
from src.repositories.billing import OrganizationBalanceCRUD
from src.schemas.billing import (
    BillingChannel,
    SBalanceTransactionListRead,
    SBillingSummaryRead,
    SBillingTariffsUpdate,
    SBillingTopUpRequest,
)


async def _billing_open(session: SessionUserDep, full_access: FullAccessDep) -> None:
    """Per-minute clients (``minutes_only``) have no billing section: 403 for
    everyone but ADMIN/SUPER_ADMIN, so a direct link or API call is closed too."""
    if full_access:
        return
    if (await OrganizationBalanceCRUD(session).get_or_create()).minutes_only:
        raise Forbidden


router = APIRouter(
    prefix="/billing",
    tags=["billing"],
    dependencies=[view_billing, Depends(_billing_open)],
)


@router.get("/summary", response_model=SBillingSummaryRead)
async def get_billing_summary(session: SessionUserDep, full_access: FullAccessDep):
    """Independent balances, available minutes/SMS, calculated costs and rates.

    The SMS rate is an internal tariff: only ADMIN/SUPER_ADMIN get it."""
    return await BillingService(session).get_summary(mask_tariffs=not full_access)


@router.post("/topup", response_model=SBillingSummaryRead, dependencies=[write_billing])
async def top_up_balance(
    session: SessionUserCommitDep,
    body: SBillingTopUpRequest,
    full_access: FullAccessDep,
):
    """Top up the selected call or SMS account only."""
    return await BillingService(session).top_up(body, mask_tariffs=not full_access)


@router.patch("/tariffs", response_model=SBillingSummaryRead, dependencies=[admin_only])
async def update_tariffs(
    session: SessionUserCommitDep,
    body: SBillingTariffsUpdate,
):
    """Internal endpoint (ADMIN/SUPER_ADMIN only) to update tariffs and the
    ``minutes_only`` billing mode. A client never sets its own tariffs."""
    return await BillingService(session).update_tariffs(body)


@router.get("/transactions", response_model=SBalanceTransactionListRead)
async def list_transactions(
    session: SessionUserDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    type: str | None = Query(None),
    channel: BillingChannel | None = Query(None),
):
    """Returns the financial transaction history."""
    return await BillingService(session).list_transactions(
        limit=limit, offset=offset, tx_type=type, channel=channel
    )
