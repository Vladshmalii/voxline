"""Campaign lifecycle and contact upload.

Upload is where a campaign's template meets real rows, so it is where template
failures must surface: every row is strict-rendered in a resource-limited
subprocess *before* any call is created (readiness philosophy — a template
that fails on row 372 must fail here, not when that phone is already
ringing). The dispatcher (``worker/dispatch.py``) does the dialing; operators
and this service only move statuses and rows.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums.campaign import (
    CallLifecycleEnum,
    CampaignStatusEnum,
    ClientStatusEnum,
)
from src.models.audience import Audience, AudienceMember
from src.models.call import Call
from src.models.campaign import Campaign
from src.models.client import Client
from src.models.messaging import Message
from src.repositories.audience import AudienceCRUD, AudienceMemberCRUD
from src.repositories.call import SMS_SENT_STATUSES, CallCRUD
from src.repositories.campaign import CampaignCRUD
from src.repositories.client import ClientCRUD
from src.schemas import admin
from src.utils.phone import normalize_phone
from src.utils.script import (
    ScriptError,
    merge_player_attributes,
    validate_rows_limited,
    validate_template,
)

#: Campaign statuses that still accept contact uploads.
UPLOADABLE = (
    CampaignStatusEnum.draft,
    CampaignStatusEnum.scheduled,
    CampaignStatusEnum.running,
    CampaignStatusEnum.paused,
)

#: Statuses a campaign can be restarted from.
RESTARTABLE = (CampaignStatusEnum.completed, CampaignStatusEnum.error)

#: Columns the Campaigns tab (VOAD-36) may sort by, keyed by the ``sort``
#: query param's field name (optionally ``-``-prefixed for descending).
_SORTABLE_FIELDS = {
    "name": Campaign.name,
    "created_at": Campaign.created_at,
    "starts_at": Campaign.starts_at,
    "status": Campaign.status,
}


class CampaignError(ValueError):
    """The operation cannot proceed; the message says why."""


class CampaignService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get(self, campaign_id: int) -> Campaign:
        campaign = await CampaignCRUD(self.session).get_one_or_none(
            Campaign.id == campaign_id
        )
        if campaign is None:
            raise CampaignError(f"campaign {campaign_id} not found")
        return campaign

    async def list(
        self,
        *,
        status: list[CampaignStatusEnum] | None = None,
        agent_id: int | None = None,
        search: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        starts_from: datetime | None = None,
        starts_to: datetime | None = None,
        include_archived: bool = False,
        sort: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Campaign], int]:
        """Filtered/sorted/paginated campaign listing for the Campaigns tab (VOAD-36).

        - ``status`` accepts multiple values (repeat the query param, e.g.
          ``?status=running&status=paused``) so the tab can show more than
          one bucket in one request; a single value works the same way.
        - ``search`` is a case-insensitive substring match on ``name``.
        - Date filters are offered on both ``created_at`` and ``starts_at``
          since the ticket names both ("created/starts_at date"); each bound
          is optional and inclusive.
        - ``sort`` is one of ``name`` / ``created_at`` / ``starts_at`` /
          ``status``, optionally ``-``-prefixed for descending (e.g.
          ``-created_at``). Omitted: unchanged from before this ticket
          (``-id``, i.e. newest first).

        Raises:
            CampaignError: ``sort`` names a field that isn't sortable.
        """
        clauses: list[ColumnElement[bool]] = []
        if status:
            clauses.append(Campaign.status.in_(status))
        if agent_id is not None:
            clauses.append(Campaign.agent_id == agent_id)
        if search:
            clauses.append(Campaign.name.icontains(search))
        if created_from is not None:
            clauses.append(Campaign.created_at >= created_from)
        if created_to is not None:
            clauses.append(Campaign.created_at <= created_to)
        if starts_from is not None:
            clauses.append(Campaign.starts_at >= starts_from)
        if starts_to is not None:
            clauses.append(Campaign.starts_at <= starts_to)
        if not include_archived:
            clauses.append(Campaign.is_archived.is_(False))

        order_by = Campaign.id.desc()
        if sort:
            field = sort.removeprefix("-")
            column = _SORTABLE_FIELDS.get(field)
            if column is None:
                raise CampaignError(f"unknown sort field: {field}")
            order_by = column.desc() if sort.startswith("-") else column.asc()

        return await CampaignCRUD(self.session).get_many_with_count(
            *clauses, order_by=order_by, limit=limit, offset=offset
        )

    async def reason_breakdown(
        self, campaign_id: int
    ) -> admin.SCampaignReasonBreakdown:
        await self._get(campaign_id)
        counts = await CallCRUD(self.session).reason_category_counts(campaign_id)
        return admin.SCampaignReasonBreakdown(
            total=sum(count for _, count in counts),
            categories=[
                admin.SReasonCategoryCount(reason_category=category, count=count)
                for category, count in counts
            ],
        )

    async def counters(self, campaign_id: int) -> admin.SCampaignCounters:
        await self._get(campaign_id)
        counts = await CallCRUD(self.session).status_counts(campaign_id)
        sms_sent = await self.session.scalar(
            select(func.count(Message.id))
            .join(Call, Call.id == Message.call_id)
            .where(
                Call.campaign_id == campaign_id,
                Message.status.in_(SMS_SENT_STATUSES),
            )
        )
        return admin.SCampaignCounters(
            total=sum(count for _, count in counts),
            sms_sent=sms_sent or 0,
            by_status=[
                admin.SCallStatusCount(status=status, count=count)
                for status, count in counts
            ],
        )

    async def create(self, data: admin.SCampaignCreate) -> Campaign:
        try:
            validate_template(data.call_script)
        except ScriptError as exc:
            raise CampaignError(f"call_script: {exc}") from exc
        return await CampaignCRUD(self.session).create(
            {
                **data.model_dump(exclude={"calling_hours", "retry"}),
                "calling_hours": data.calling_hours.model_dump(
                    mode="json", exclude_unset=True
                )
                if data.calling_hours
                else {},
                "retry": data.retry.model_dump(mode="json", exclude_unset=True)
                if data.retry
                else {},
            }
        )

    async def update(self, campaign_id: int, data: admin.SCampaignUpdate) -> Campaign:
        campaign = await self._get(campaign_id)
        if data.is_archived and campaign.status == CampaignStatusEnum.running:
            raise CampaignError(
                "cannot archive a running campaign — pause or complete it first"
            )
        values = data.model_dump(exclude_unset=True, exclude={"calling_hours", "retry"})
        if "call_script" in values:
            try:
                validate_template(values["call_script"])
            except ScriptError as exc:
                raise CampaignError(f"call_script: {exc}") from exc
        if data.calling_hours is not None:
            values["calling_hours"] = data.calling_hours.model_dump(
                mode="json", exclude_unset=True
            )
        if data.retry is not None:
            values["retry"] = data.retry.model_dump(mode="json", exclude_unset=True)
        if values:
            await CampaignCRUD(self.session).update(
                Campaign.id == campaign_id, data=values
            )
            self.session.expire(campaign)
        return await self._get(campaign_id)

    async def add_audience(
        self, campaign_id: int, audience_id: int
    ) -> list[admin.SCampaignUploadResult]:
        """Add every member of an audience to this campaign.

        Goes through :meth:`upload`, the exact path a direct CSV/JSON upload
        takes — so a member already added to this campaign on a previous call
        (the audience grew since, or this is a re-run) is rejected the same
        way a duplicate row always is, and everything else runs the campaign's
        own template check.
        """
        if (
            await AudienceCRUD(self.session).get_one_or_none(Audience.id == audience_id)
            is None
        ):
            raise CampaignError(f"audience {audience_id} not found")
        members = await AudienceMemberCRUD(self.session).get_many_ordered(
            AudienceMember.audience_id == audience_id
        )
        rows = [
            admin.SCampaignContactRow(
                phone=member.client.phone,
                name=member.client.name,
                language=member.language,
                bonuses=member.bonuses,
                player_id=member.player_id,
                vip_status=member.vip_status,
                last_deposit=member.last_deposit,
                last_active=member.last_active,
                country=member.country,
                timezone=member.timezone,
                attributes=member.attributes,
            )
            for member in members
        ]
        return await self.upload(campaign_id, rows)

    async def upload(
        self, campaign_id: int, rows: list[admin.SCampaignContactRow]
    ) -> list[admin.SCampaignUploadResult]:
        """Create the campaign's calls from uploaded contacts, all-checked first.

        Per row: normalize the phone, strict-render the campaign template with
        the row's parameters, upsert the client, refuse non-callable clients
        and duplicates, create a ``pending`` call with the script inputs
        pinned. Rejected rows come back with the reason; accepted ones with
        their call id.
        """
        campaign = await self._get(campaign_id)
        if campaign.status not in UPLOADABLE:
            raise CampaignError(
                f"campaign {campaign_id} is {campaign.status}; upload refused"
            )

        results: list[admin.SCampaignUploadResult] = []
        phones: list[str | None] = []
        for row in rows:
            try:
                phones.append(normalize_phone(row.phone))
            except ValueError as exc:
                phones.append(None)
                results.append(
                    admin.SCampaignUploadResult(phone=row.phone, error=str(exc))
                )

        renderable = [
            (index, row) for index, row in enumerate(rows) if phones[index] is not None
        ]
        try:
            render_errors = await validate_rows_limited(
                campaign.call_script,
                [
                    {
                        "name": row.name or "",
                        "bonuses": row.bonuses,
                        "attributes": merge_player_attributes(
                            row.attributes,
                            player_id=row.player_id,
                            vip_status=row.vip_status,
                            last_deposit=row.last_deposit,
                            last_active=row.last_active,
                            country=row.country,
                            timezone=row.timezone,
                        ),
                    }
                    for _, row in renderable
                ],
            )
        except ScriptError as exc:
            raise CampaignError(f"call_script: {exc}") from exc

        clients = ClientCRUD(self.session)
        calls = CallCRUD(self.session)
        for (index, row), render_error in zip(renderable, render_errors):
            phone = phones[index]
            if render_error is not None:
                results.append(
                    admin.SCampaignUploadResult(
                        phone=phone, error=f"call_script: {render_error}"
                    )
                )
                continue
            client = await clients.upsert_by_phone(phone, row.name)
            if client.status != ClientStatusEnum.active:
                results.append(
                    admin.SCampaignUploadResult(
                        phone=phone, error=f"client is not callable ({client.status})"
                    )
                )
                continue
            duplicate = await self.session.scalar(
                select(Call.id).where(
                    Call.campaign_id == campaign.id,
                    Call.client_id == client.id,
                    Call.status.in_(
                        (CallLifecycleEnum.pending, CallLifecycleEnum.calling)
                    ),
                )
            )
            if duplicate is not None:
                results.append(
                    admin.SCampaignUploadResult(
                        phone=phone, error="already in this campaign"
                    )
                )
                continue
            call = await calls.create(
                {
                    "client_id": client.id,
                    "campaign_id": campaign.id,
                    "agent_id": campaign.agent_id,
                    "status": CallLifecycleEnum.pending,
                    "language": row.language,
                    "attributes": row.attributes,
                    "bonuses": row.bonuses,
                    "player_id": row.player_id,
                    "vip_status": row.vip_status,
                    "last_deposit": row.last_deposit,
                    "last_active": row.last_active,
                    "country": row.country,
                    "timezone": row.timezone,
                }
            )
            results.append(admin.SCampaignUploadResult(phone=phone, call_id=call.id))
        return results

    @staticmethod
    def _check_dialable(campaign: Campaign) -> None:
        """Preflight shared by start and restart: agent, telephony, script."""
        agent = campaign.agent
        if not agent.is_active:
            raise CampaignError(f"agent {agent.id} is not active")
        if agent.telephony is None or not agent.telephony.is_active:
            raise CampaignError(f"agent {agent.id} has no active telephony binding")
        try:
            validate_template(campaign.call_script)
        except ScriptError as exc:
            raise CampaignError(f"call_script: {exc}") from exc

    async def start(self, campaign_id: int) -> Campaign:
        """Start (or schedule, when ``starts_at`` is in the future) a campaign.

        Refuses configurations a call would fail on — the same "surface it at
        config time" rule the readiness probe applies to agents.
        """
        campaign = await self._get(campaign_id)
        if campaign.status == CampaignStatusEnum.completed:
            raise CampaignError("campaign is completed")
        self._check_dialable(campaign)

        starts_later = (
            campaign.starts_at is not None and campaign.starts_at > datetime.now()
        )
        campaign.status = (
            CampaignStatusEnum.scheduled if starts_later else CampaignStatusEnum.running
        )
        return campaign

    async def restart(self, campaign_id: int) -> Campaign:
        """Re-run a finished campaign over its undelivered calls.

        Allowed from ``completed`` / ``error`` only. Calls that ended
        ``exhausted`` or ``canceled`` (client still active) go back to
        ``pending``; ``completed``/``blocked``/``calling`` calls are left
        alone. ``attempts_made`` is kept (attempt ``seq`` must stay unique);
        ``attempt_base`` marks where the new retry budget starts. The status
        flip is a guarded UPDATE so a concurrent second restart gets 422 and
        cannot reset twice.
        """
        campaign = await self._get(campaign_id)
        if campaign.status not in RESTARTABLE:
            raise CampaignError(f"campaign is {campaign.status}; restart refused")
        if campaign.ends_at is not None and campaign.ends_at <= datetime.now():
            raise CampaignError("campaign ends_at is in the past; restart refused")
        self._check_dialable(campaign)

        starts_later = (
            campaign.starts_at is not None and campaign.starts_at > datetime.now()
        )
        new_status = (
            CampaignStatusEnum.scheduled if starts_later else CampaignStatusEnum.running
        )
        claimed = await self.session.execute(
            update(Campaign)
            .where(Campaign.id == campaign.id, Campaign.status.in_(RESTARTABLE))
            .values(status=new_status)
            .returning(Campaign.id)
        )
        if claimed.first() is None:
            await self.session.refresh(campaign, ["status"])
            raise CampaignError(f"campaign is {campaign.status}; restart refused")

        await self.session.execute(
            update(Call)
            .where(
                Call.campaign_id == campaign.id,
                Call.status.in_(
                    (CallLifecycleEnum.exhausted, CallLifecycleEnum.canceled)
                ),
                Call.client_id.in_(
                    select(Client.id).where(Client.status == ClientStatusEnum.active)
                ),
            )
            .values(
                status=CallLifecycleEnum.pending,
                attempt_base=Call.attempts_made,
                next_attempt_at=None,
                is_callback=False,
                outcome=None,
                selected_offer=None,
                sentiment=None,
                reason_category=None,
                tags=[],
            )
            .execution_options(synchronize_session=False)
        )
        campaign.status = new_status
        return campaign

    async def pause(self, campaign_id: int) -> Campaign:
        campaign = await self._get(campaign_id)
        if campaign.status not in (
            CampaignStatusEnum.scheduled,
            CampaignStatusEnum.running,
        ):
            raise CampaignError(f"campaign is {campaign.status}; pause refused")
        campaign.status = CampaignStatusEnum.paused
        return campaign

    async def mark_error(self, campaign_id: int) -> Campaign:
        """Move a campaign to ``error`` by hand (VOAD-36 interim path).

        The natural home for *automatic* detection — "this campaign's setup
        just became undialable at runtime" — is the dispatcher
        (``worker/dispatch.py``, VOAD-33 territory, out of scope here). Until
        that lands, this gives operators an explicit way to flag a campaign
        as ``error`` themselves, e.g. after noticing its agent or telephony
        binding broke mid-run. Refused only once the campaign is
        ``completed`` — a finished campaign's history should not be
        rewritten; every other status (including ``error`` itself) accepts
        it, so a re-flag is a harmless no-op.
        """
        campaign = await self._get(campaign_id)
        if campaign.status == CampaignStatusEnum.completed:
            raise CampaignError(f"campaign is {campaign.status}; cannot mark as error")
        campaign.status = CampaignStatusEnum.error
        return campaign

    async def complete(self, campaign_id: int) -> Campaign:
        """Finish a campaign by hand: remaining pending calls are canceled."""
        campaign = await self._get(campaign_id)
        if campaign.status == CampaignStatusEnum.completed:
            return campaign
        await self.session.execute(
            update(Call)
            .where(
                Call.campaign_id == campaign.id,
                Call.status == CallLifecycleEnum.pending,
            )
            .values(status=CallLifecycleEnum.canceled)
        )
        campaign.status = CampaignStatusEnum.completed
        return campaign

    async def delete(self, campaign_id: int) -> None:
        """Delete a campaign that has never dialed anyone.

        Refused once a call exists for it (``Call.campaign_id`` is
        ``ondelete="RESTRICT"``) — call history must survive the campaign
        that made it, so this is refused with a clear reason rather than
        surfacing the database's own integrity error.
        """
        await self._get(campaign_id)
        has_calls = await self.session.scalar(
            select(exists().where(Call.campaign_id == campaign_id))
        )
        if has_calls:
            raise CampaignError(
                f"campaign {campaign_id} has calls; it cannot be deleted"
            )
        await CampaignCRUD(self.session).delete(Campaign.id == campaign_id)
