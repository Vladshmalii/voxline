from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.billing import BillingService
from src.application.services.services_status import ServicesStatusService
from src.application.services.stats import StatsService
from src.common.enums.campaign import CallOutcomeEnum, CampaignStatusEnum
from src.schemas.admin_stats import SAdminAccountStatsRead


class AdminStatsService:
    def __init__(self, session: AsyncSession, org_uuid: str) -> None:
        self.session = session
        self.org_uuid = org_uuid

    async def get_account_stats(self) -> SAdminAccountStatsRead:
        now = datetime.now(UTC)
        stats_svc = StatsService(self.session)
        billing_svc = BillingService(self.session)
        services_svc = ServicesStatusService(self.session)

        stats_data = await stats_svc.overview()
        billing_data = await billing_svc.get_summary()
        services_data = await services_svc.get_status()

        # Running campaigns count
        running_campaigns = sum(
            c.count
            for c in stats_data.campaigns.by_status
            if c.status == CampaignStatusEnum.running
        )

        # Successful vs unsuccessful — "successful" is the org's own
        # definition: a follow-up SMS was sent after the call, not the
        # call's telephony status (see StatsService.overview/successful).
        total_calls = stats_data.calls.total
        completed_calls = stats_data.calls.successful
        failed_calls = max(0, total_calls - completed_calls)

        # Conversion rate (converted outcome / total calls if total > 0)
        converted_calls = sum(
            o.count
            for o in stats_data.calls.by_outcome
            if o.outcome == CallOutcomeEnum.converted
        )
        conversion_rate = (converted_calls / total_calls) if total_calls > 0 else 0.0

        return SAdminAccountStatsRead(
            organization_uuid=self.org_uuid,
            generated_at=now,
            # Resources
            agents_total=stats_data.agents.total,
            agents_active=stats_data.agents.active,
            campaigns_total=stats_data.campaigns.total,
            campaigns_running=running_campaigns,
            audiences_total=0,  # can be expanded
            leads_total=stats_data.clients.total,
            # Calls
            calls_total=total_calls,
            calls_completed=completed_calls,
            calls_failed=failed_calls,
            answer_rate=stats_data.calls.answer_rate,
            conversion_rate=conversion_rate,
            total_duration_minutes=billing_data.total_minutes_used,
            avg_duration_seconds=stats_data.calls.avg_duration_seconds,
            # Billing
            current_balance=billing_data.balance,
            call_balance=billing_data.call_balance,
            sms_balance=billing_data.sms_balance,
            currency=billing_data.currency,
            remaining_minutes=billing_data.remaining_minutes,
            total_spent=billing_data.total_spent,
            total_deposited=billing_data.total_deposited,
            cost_per_minute=billing_data.cost_per_minute,
            cost_per_sms=billing_data.cost_per_sms,
            total_sms_sent=billing_data.total_sms_sent,
            # Infrastructure
            services_status=services_data.status,
            telephony_operational=services_data.telephony_operational,
            telephony_gateways_count=services_data.telephony_count,
            active_models_count=services_data.models_count,
            sms_routes_count=1 if services_data.messaging_operational else 0,
        )
