from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

BillingChannel = Literal["calls", "sms"]


class SBillingSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Kept for legacy clients as the call balance. New clients use the two
    # explicit balances; there is no shared pool of funds.
    balance: float
    call_balance: float
    sms_balance: float
    currency: str
    cost_per_minute: float
    # None for non-admin callers: clients never see the SMS rate.
    cost_per_sms: float | None
    minutes_only: bool = False
    remaining_minutes: float
    remaining_sms: int
    call_spent: float
    sms_spent: float
    call_deposited: float
    sms_deposited: float
    total_spent: float
    total_deposited: float
    total_minutes_used: float
    total_calls_count: int
    total_sms_sent: int


class SBillingTopUpRequest(BaseModel):
    channel: BillingChannel = "calls"
    amount: float = Field(
        ..., gt=0, allow_inf_nan=False, description="Amount to add to the balance"
    )
    description: str = Field("Manual top up by administrator", min_length=1)


class SBillingTariffsUpdate(BaseModel):
    cost_per_minute: float | None = Field(None, ge=0, allow_inf_nan=False)
    cost_per_sms: float | None = Field(None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(None, max_length=10)
    minutes_only: bool | None = None


class SBalanceTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    amount: float
    type: str
    channel: BillingChannel
    description: str
    call_id: int | None = None
    sms_id: int | None = None
    admin_id: int | None = None
    balance_after: float | None = None
    legacy_balance_after: float | None = None
    created_at: datetime


class SBalanceTransactionListRead(BaseModel):
    data: list[SBalanceTransactionRead]
    count: int
