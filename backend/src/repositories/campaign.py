"""Campaign repository, plus the row → section parsing.

Same boundary rule as the agent's engine sections: JSONB is validated through
the pydantic section models here, where an error names the row, and ``{}``
means the section's defaults.
"""

from sqlalchemy import func, select

from src.common.enums.campaign import CampaignStatusEnum
from src.models.campaign import Campaign
from src.repositories.base import CRUD
from src.schemas.campaign import CallingHours, RetryPolicy


def campaign_hours(row: Campaign) -> CallingHours:
    return CallingHours(**row.calling_hours)


def campaign_retry(row: Campaign) -> RetryPolicy:
    return RetryPolicy(**row.retry)


class CampaignCRUD(CRUD[Campaign]):
    model = Campaign

    async def total_count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Campaign))
        return result.scalar_one()

    async def global_status_counts(self) -> list[tuple[CampaignStatusEnum, int]]:
        """Every campaign grouped by lifecycle status (VOAD-38 dashboard)."""
        rows = await self.session.execute(
            select(Campaign.status, func.count()).group_by(Campaign.status)
        )
        return list(rows.all())
