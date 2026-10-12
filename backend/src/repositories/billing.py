from __future__ import annotations

from sqlalchemy import func, select

from src.models.billing import BalanceTransaction, OrganizationBalance
from src.repositories.base import CRUD
from src.schemas.billing import BillingChannel


class OrganizationBalanceCRUD(CRUD[OrganizationBalance]):
    model = OrganizationBalance

    async def get_or_create(self) -> OrganizationBalance:
        """Returns the organization's single balance record, creating default if not present."""
        result = await self.session.execute(select(OrganizationBalance).limit(1))
        balance_row = result.scalar_one_or_none()
        if balance_row is None:
            # Serialize only first-time initialization in this tenant DB.
            # Two first deposits must land on the same account row.
            await self.session.execute(select(func.pg_advisory_xact_lock(867942130)))
            result = await self.session.execute(select(OrganizationBalance).limit(1))
            balance_row = result.scalar_one_or_none()
        if balance_row is None:
            balance_row = OrganizationBalance(
                currency="USD",
                call_balance=0.0,
                sms_balance=0.0,
                cost_per_minute=0.10,
                cost_per_sms=0.02,
            )
            self.session.add(balance_row)
            await self.session.flush()
        return balance_row


class BalanceTransactionCRUD(CRUD[BalanceTransaction]):
    model = BalanceTransaction

    async def list_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        tx_type: str | None = None,
        channel: BillingChannel | None = None,
    ) -> tuple[list[BalanceTransaction], int]:
        clauses = []
        if tx_type == "charges":
            clauses.append(BalanceTransaction.amount < 0)
        elif tx_type:
            clauses.append(BalanceTransaction.type == tx_type)
        if channel:
            clauses.append(BalanceTransaction.channel == channel)
        return await self.get_many_with_count(
            *clauses,
            order_by=BalanceTransaction.id.desc(),
            limit=limit,
            offset=offset,
        )
