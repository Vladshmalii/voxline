"""Stats router (VOAD-38): read-only snapshots for the dashboard.

Everything here is assembled by ``StatsService`` from a handful of
GROUP BY/COUNT queries — see that module's own docstring.
"""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from src.application.services.stats import StatsService
from src.controller.dependencies.db import SessionUserDep
from src.controller.dependencies.permission import view_dashboard
from src.schemas import admin

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[view_dashboard])

MAX_TIMESERIES_SPAN_DAYS = 90


@router.get("/overview", response_model=admin.SStatsOverview)
async def stats_overview(session: SessionUserDep):
    return await StatsService(session).overview()


@router.get("/active-geo", response_model=admin.SActiveGeoOverview)
async def stats_active_geo(session: SessionUserDep):
    return await StatsService(session).active_geo()


@router.get("/timeseries", response_model=admin.SStatsTimeseries)
async def stats_timeseries(
    session: SessionUserDep,
    date_from: date = Query(...),
    date_to: date = Query(...),
):
    if date_to < date_from:
        raise HTTPException(422, "date_to must not be before date_from")
    if (date_to - date_from) > timedelta(days=MAX_TIMESERIES_SPAN_DAYS):
        raise HTTPException(
            422, f"range may not exceed {MAX_TIMESERIES_SPAN_DAYS} days"
        )
    return await StatsService(session).timeseries(date_from=date_from, date_to=date_to)
