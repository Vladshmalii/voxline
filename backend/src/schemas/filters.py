"""History filters — the query string of a list page, as one object.

A listing and its file export take the same filters, so they are declared once
here and read by the history services rather than as per-route ``Query``
parameters that two routes would have to keep in step.

Each route takes exactly one of the ``*Query`` models below as
``Annotated[…, Query()]``: FastAPI spreads a model over the query string (and
over the OpenAPI parameters) only when it is the route's *sole* query
parameter, so paging and export options are fields here too, not ``Query``
arguments beside the model.

Datetimes are stored naive UTC, so explicit offsets are converted on the way
in; a naive value is taken to be UTC already.
"""

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from src.common.enums.campaign import (
    CallLifecycleEnum,
    CallOutcomeEnum,
    ClientSegmentEnum,
    ClientStatusEnum,
    ReasonCategoryEnum,
    SentimentEnum,
)
from src.common.enums.engine import (
    CallDirectionEnum,
    CallStatusEnum,
    MessageStatusEnum,
)
from src.common.enums.export import ExportFormatEnum
from src.utils.timezone import to_utc_naive


class _CreationRange(BaseModel):
    date_from: date | None = Field(None, description="Inclusive creation day, UTC")
    date_to: date | None = Field(None, description="Inclusive creation day, UTC")
    created_from: datetime | None = Field(
        None, description="Inclusive creation time, UTC"
    )
    created_to: datetime | None = Field(
        None, description="Inclusive creation time, UTC"
    )

    @field_validator("created_from", "created_to")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return to_utc_naive(value)

    @model_validator(mode="after")
    def _ordered(self):
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        if (
            self.created_from
            and self.created_to
            and self.created_to < self.created_from
        ):
            raise ValueError("created_to must not be before created_from")
        return self


class SSmsFilters(_CreationRange):
    messaging_id: int | None = Field(None, ge=1)
    status: MessageStatusEnum | None = None
    to: str | None = Field(None, max_length=128, description="Exact destination, E.164")
    to_search: str | None = Field(
        None, max_length=128, description="Destination substring"
    )
    search: str | None = Field(
        None, max_length=1600, description="Literal, case-insensitive body substring"
    )
    sender: str | None = Field(None, max_length=128, description="Sender substring")
    agent_id: int | None = Field(None, ge=1)
    campaign_id: int | None = Field(None, ge=1)
    call_id: int | None = Field(None, ge=1)
    source: Literal["call", "manual"] | None = Field(
        None, description="Linked to a call or sent outside a call"
    )
    sort: Literal["newest", "oldest"] = "newest"


class SCallFilters(_CreationRange):
    agent_id: int | None = Field(None, ge=1)
    campaign_id: int | None = Field(None, ge=1)
    client_id: int | None = Field(None, ge=1)
    call_id: int | None = Field(None, ge=1)
    status: CallLifecycleEnum | None = None
    attempt_status: CallStatusEnum | None = Field(
        None, description="Status of the call's latest attempt"
    )
    outcome: CallOutcomeEnum | None = None
    sentiment: SentimentEnum | None = None
    reason_category: ReasonCategoryEnum | None = None
    direction: CallDirectionEnum | None = None
    search: str | None = Field(
        None,
        max_length=1600,
        description="Literal, case-insensitive speech or summary substring, across all attempts",
    )
    client_search: str | None = Field(
        None, max_length=128, description="Client name or destination number substring"
    )
    from_search: str | None = Field(
        None, max_length=128, description="Caller number substring"
    )
    language: str | None = Field(None, max_length=32)
    has_recording: bool | None = Field(
        None, description="Any attempt has a stored recording URL"
    )
    #: Legacy free-form names (``id``, ``-created_at``, ``duration``…); an
    #: unknown one falls back to newest-first, as it always has.
    sort: str | None = None


class SClientFilters(BaseModel):
    """The lead table's filters (VOAD-34).

    Every one is a persistent ``Client`` fact. The ``last_active`` bounds are
    compared as given, not converted to UTC like the history filters above.
    """

    phone: str | None = Field(None, description="Substring match on phone only.")
    search: str | None = Field(
        None,
        description="Case-insensitive substring match on phone OR name — the "
        "lead table's free-text search box (VOAD-34).",
    )
    status: ClientStatusEnum | None = None
    segment: ClientSegmentEnum | None = None
    country: str | None = None
    language: str | None = None
    vip_status: str | None = None
    last_active_from: datetime | None = None
    last_active_to: datetime | None = None
    last_deposit_min: float | None = None
    last_deposit_max: float | None = None
    audience_id: int | None = Field(
        None,
        description="Restrict to clients who are members of this audience — "
        "the closest available notion of 'leads from one upload batch' "
        "(VOAD-34), since membership isn't tagged with the individual upload "
        "event that added it (see AudienceUpload's docstring).",
    )


class _Page(BaseModel):
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)


class _ExportOptions(BaseModel):
    format: ExportFormatEnum = ExportFormatEnum.csv
    tz: str = Field(
        "UTC",
        max_length=64,
        description="IANA zone the file's datetimes are written in; filters stay UTC",
    )

    @field_validator("tz")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone: {value}") from None
        return value

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


class SSmsListQuery(SSmsFilters, _Page):
    pass


class SSmsExportQuery(SSmsFilters, _ExportOptions):
    pass


class SCallListQuery(SCallFilters, _Page):
    pass


class SCallExportQuery(SCallFilters, _ExportOptions):
    pass


class SClientListQuery(_Page, SClientFilters):
    # Bases reversed vs. the history queries: paging stays last in the
    # OpenAPI parameter list, where it was as separate ``Query`` arguments.
    pass
