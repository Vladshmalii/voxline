from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums.engine import MessageStatusEnum
from src.models.billing import BalanceTransaction, OrganizationBalance
from src.models.call import Call, CallAttempt
from src.models.messaging import Message
from src.repositories.billing import BalanceTransactionCRUD, OrganizationBalanceCRUD
from src.schemas.billing import (
    BillingChannel,
    SBalanceTransactionListRead,
    SBalanceTransactionRead,
    SBillingSummaryRead,
    SBillingTariffsUpdate,
    SBillingTopUpRequest,
)


class BillingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.balance_crud = OrganizationBalanceCRUD(session)
        self.tx_crud = BalanceTransactionCRUD(session)

    async def get_summary(self, *, mask_tariffs: bool = False) -> SBillingSummaryRead:
        bal = await self.balance_crud.get_or_create()

        # Total duration of connected calls (in seconds)
        duration_res = await self.session.execute(
            select(
                func.sum(
                    func.extract(
                        "epoch", CallAttempt.ended_at - CallAttempt.answered_at
                    )
                ),
                func.count(func.distinct(Call.id)),
            )
            .select_from(CallAttempt)
            .outerjoin(Call, CallAttempt.call_id == Call.id)
            .where(
                CallAttempt.answered_at.is_not(None),
                CallAttempt.ended_at.is_not(None),
            )
        )
        total_seconds, total_calls = duration_res.one()
        total_seconds = float(total_seconds or 0.0)
        total_minutes = round(total_seconds / 60.0, 2)
        total_calls = int(total_calls or 0)

        # Total SMS sent
        sms_res = await self.session.execute(
            select(func.count(Message.id)).where(
                Message.status.in_(
                    [
                        MessageStatusEnum.sent,
                        MessageStatusEnum.delivered,
                        MessageStatusEnum.undelivered,
                    ]
                )
            )
        )
        total_sms = int(sms_res.scalar_one() or 0)

        # Total deposited sum from transactions
        deposit_res = await self.session.execute(
            select(BalanceTransaction.channel, func.sum(BalanceTransaction.amount))
            .where(BalanceTransaction.type == "deposit")
            .group_by(BalanceTransaction.channel)
        )
        deposits = dict(deposit_res.all())
        call_deposited = float(deposits.get("calls", 0.0))
        sms_deposited = float(deposits.get("sms", 0.0))
        total_deposited = call_deposited + sms_deposited

        # Total spent calculation
        call_spent = total_minutes * bal.cost_per_minute
        sms_spent = total_sms * bal.cost_per_sms
        total_spent = round(call_spent + sms_spent, 2)

        # Remaining minutes with current balance
        remaining_minutes = (
            round(bal.call_balance / bal.cost_per_minute, 1)
            if bal.cost_per_minute > 0 and bal.call_balance > 0
            else 0.0
        )

        return SBillingSummaryRead(
            balance=round(bal.call_balance, 2),
            call_balance=round(bal.call_balance, 2),
            sms_balance=round(bal.sms_balance, 2),
            currency=bal.currency,
            cost_per_minute=bal.cost_per_minute,
            cost_per_sms=None if mask_tariffs else bal.cost_per_sms,
            minutes_only=bal.minutes_only,
            remaining_minutes=remaining_minutes,
            remaining_sms=int(
                Decimal(str(bal.sms_balance)) / Decimal(str(bal.cost_per_sms))
            )
            if bal.cost_per_sms > 0 and bal.sms_balance > 0
            else 0,
            call_spent=round(call_spent, 2),
            sms_spent=round(sms_spent, 2),
            call_deposited=round(call_deposited, 2),
            sms_deposited=round(sms_deposited, 2),
            total_spent=total_spent,
            total_deposited=round(total_deposited, 2),
            total_minutes_used=total_minutes,
            total_calls_count=total_calls,
            total_sms_sent=total_sms,
        )

    async def top_up(
        self,
        req: SBillingTopUpRequest,
        admin_id: int | None = None,
        *,
        mask_tariffs: bool = False,
    ) -> SBillingSummaryRead:
        bal = await self.balance_crud.get_or_create()
        column = (
            OrganizationBalance.call_balance
            if req.channel == "calls"
            else OrganizationBalance.sms_balance
        )
        # Increment inside the DB so simultaneous deposits cannot overwrite
        # one another. RETURNING pins balance_after to this deposit.
        balance_after = (
            await self.session.execute(
                update(OrganizationBalance)
                .where(OrganizationBalance.id == bal.id)
                .values({column: column + req.amount})
                .returning(column)
            )
        ).scalar_one()

        tx = BalanceTransaction(
            amount=req.amount,
            type="deposit",
            channel=req.channel,
            description=req.description,
            admin_id=admin_id,
            balance_after=balance_after,
        )
        self.session.add(tx)
        await self.session.flush()

        return await self.get_summary(mask_tariffs=mask_tariffs)

    async def update_tariffs(self, req: SBillingTariffsUpdate) -> SBillingSummaryRead:
        bal = await self.balance_crud.get_or_create()
        if req.cost_per_minute is not None:
            bal.cost_per_minute = req.cost_per_minute
        if req.cost_per_sms is not None:
            bal.cost_per_sms = req.cost_per_sms
        if req.currency is not None:
            bal.currency = req.currency
        if req.minutes_only is not None:
            bal.minutes_only = req.minutes_only

        await self.session.flush()
        return await self.get_summary()

    async def list_transactions(
        self,
        limit: int = 50,
        offset: int = 0,
        tx_type: str | None = None,
        channel: BillingChannel | None = None,
    ) -> SBalanceTransactionListRead:
        items, total = await self.tx_crud.list_recent(
            limit=limit, offset=offset, tx_type=tx_type, channel=channel
        )
        return SBalanceTransactionListRead(
            data=[SBalanceTransactionRead.model_validate(item) for item in items],
            count=total,
        )
