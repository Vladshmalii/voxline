"""VOAD-38: one global snapshot for the frontend's stats dashboard.

Everything here is read-only and assembled from a handful of GROUP BY/COUNT
queries (see repositories/{call,campaign,client,agent}.py's "global_*"/
"total_count" methods) — no new table, no background job. Kept as its own
service (not folded into CampaignService/etc.) because it reads across every
domain at once instead of owning one of them.

``timeseries`` is a second, separate read (its own request from the
frontend) for the dashboard's calls-over-time trend — kept out of
``overview`` so a range change doesn't re-fetch the whole snapshot.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.campaign import Campaign
from src.models.messaging import Message
from src.repositories.agent import VoiceAgentCRUD
from src.repositories.call import CallCRUD
from src.repositories.campaign import CampaignCRUD
from src.repositories.client import ClientCRUD
from src.schemas import admin


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(self) -> admin.SStatsOverview:
        calls = CallCRUD(self.session)
        campaigns = CampaignCRUD(self.session)
        clients = ClientCRUD(self.session)
        agents = VoiceAgentCRUD(self.session)

        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        campaign_status_counts = await campaigns.global_status_counts()
        top_campaigns = await calls.top_campaigns_by_calls()
        # top_campaigns is (campaign_id, count) — one extra lookup for names,
        # not a join in the GROUP BY query itself, so a busiest-list of 5
        # doesn't force every row's Campaign to be selected/joined.
        campaign_names: dict[int, str] = {}
        if top_campaigns:
            rows = await campaigns.get_many_ordered(
                Campaign.id.in_([campaign_id for campaign_id, _ in top_campaigns])
            )
            campaign_names = {row.id: row.name for row in rows}

        calls_total, calls_today = await calls.headline_counts(midnight)
        avg_duration_seconds, answer_rate = await calls.attempt_headline_stats()
        _, calls_successful = await calls.success_headline_counts()
        agents_total = await agents.total_count()
        agents_active = await agents.active_count()
        messages_sent = (
            await self.session.execute(
                select(func.count(Message.id)).where(Message.status != "failed")
            )
        ).scalar_one()

        return admin.SStatsOverview(
            calls=admin.SCallStatsOverview(
                total=calls_total,
                today=calls_today,
                avg_duration_seconds=avg_duration_seconds,
                answer_rate=answer_rate,
                successful=calls_successful,
                by_status=[
                    admin.SCallStatusCount(status=status, count=count)
                    for status, count in await calls.global_status_counts()
                ],
                by_outcome=[
                    admin.SCallOutcomeCount(outcome=outcome, count=count)
                    for outcome, count in await calls.global_outcome_counts()
                ],
                by_sentiment=[
                    admin.SSentimentCount(sentiment=sentiment, count=count)
                    for sentiment, count in await calls.global_sentiment_counts()
                ],
                by_reason_category=[
                    admin.SReasonCategoryCount(reason_category=category, count=count)
                    for category, count in await calls.global_reason_category_counts()
                ],
                by_direction=[
                    admin.SDirectionCount(direction=direction, count=count)
                    for direction, count in await calls.global_direction_counts()
                ],
            ),
            campaigns=admin.SCampaignStatsOverview(
                total=await campaigns.total_count(),
                by_status=[
                    admin.SCampaignStatusCount(status=status, count=count)
                    for status, count in campaign_status_counts
                ],
                top_by_calls=[
                    admin.SCampaignTopByCalls(
                        campaign_id=campaign_id,
                        name=campaign_names.get(campaign_id, f"#{campaign_id}"),
                        calls=count,
                    )
                    for campaign_id, count in top_campaigns
                ],
            ),
            clients=admin.SClientStatsOverview(
                total=await clients.total_count(),
                by_segment=[
                    admin.SClientSegmentCount(segment=segment, count=count)
                    for segment, count in await clients.global_segment_counts()
                ],
                by_status=[
                    admin.SClientStatusCount(status=status, count=count)
                    for status, count in await clients.global_status_counts()
                ],
            ),
            agents=admin.SAgentStatsOverview(
                total=agents_total,
                active=agents_active,
                inactive=agents_total - agents_active,
            ),
            messages_sent=messages_sent,
        )

    async def active_geo(self) -> admin.SActiveGeoOverview:
        """GEOs currently being called (VOAD-55 dashboard block)."""
        calls = CallCRUD(self.session)
        return admin.SActiveGeoOverview(
            countries=[
                admin.SActiveGeoCount(
                    country=country, campaigns=campaigns, calls=calls_count
                )
                for country, campaigns, calls_count in await calls.active_geo_counts()
            ]
        )

    async def timeseries(
        self, date_from: date, date_to: date
    ) -> admin.SStatsTimeseries:
        """Calls-per-day trend for the dashboard's line chart.

        Args:
            date_from: First day, inclusive.
            date_to: Last day, inclusive. The router caps the span at 90 days.
        """
        calls = CallCRUD(self.session)
        return admin.SStatsTimeseries(
            days=[
                admin.SCallDailyCount(
                    date=day,
                    total=total,
                    completed=successful,
                    success=successful,
                    failed=failed,
                )
                for day, total, successful, failed in await calls.daily_counts(
                    date_from, date_to
                )
            ]
        )
