from datetime import date

from pydantic import BaseModel

from src.common.enums.engine import MessageStatusEnum


class SMessageStatusCount(BaseModel):
    status: MessageStatusEnum
    count: int


class SSmsStatsOverview(BaseModel):
    total: int
    today: int
    sent: int
    delivered: int
    errors: int
    pending: int
    segments: int
    # Delivered / total messages, including failures, pending and canceled.
    # None only when there are no messages in the selected scope.
    delivery_rate: float | None
    by_status: list[SMessageStatusCount]


class SSmsDailyCount(BaseModel):
    date: date
    total: int
    delivered: int
    failed: int


class SSmsStatsTimeseries(BaseModel):
    days: list[SSmsDailyCount]
