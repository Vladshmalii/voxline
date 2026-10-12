from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SAdminAccountStatsRead(BaseModel):
    organization_uuid: str
    generated_at: datetime

    # Resources
    agents_total: int
    agents_active: int
    campaigns_total: int
    campaigns_running: int
    audiences_total: int
    leads_total: int

    # Calls & Performance
    calls_total: int
    calls_completed: int
    calls_failed: int
    answer_rate: float | None = None
    conversion_rate: float | None = None
    total_duration_minutes: float
    avg_duration_seconds: float | None = None

    # Billing & Finances
    current_balance: float
    call_balance: float
    sms_balance: float
    currency: str
    remaining_minutes: float
    total_spent: float
    total_deposited: float
    cost_per_minute: float
    cost_per_sms: float
    total_sms_sent: int

    # Infrastructure status
    services_status: str
    telephony_operational: bool
    telephony_gateways_count: int
    active_models_count: int
    sms_routes_count: int
