"""The lead table (VOAD-34): clients as an operator reads and edits them.

Clients are created by upsert wherever a phone number enters the system; this
service reads them — with the two facts a lead row shows that are not
``Client`` columns, audience membership and answered calls — and edits what an
operator owns. The segmentation CSV import is ``ClientImportService``.
"""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audience import AudienceMember
from src.models.client import Client
from src.repositories.audience import AudienceMemberCRUD
from src.repositories.call import CallCRUD
from src.repositories.client import ClientCRUD
from src.schemas import admin
from src.schemas.filters import SClientFilters

#: Same junk characters utils.phone.normalize_phone strips before storing a
#: number — a search term typed with spaces/dashes/parens (e.g. "926 123-45-
#: 67") would otherwise never substring-match the stored "+79261234567".
#: Only applied to the phone half of the search; name matching stays as-is.
_PHONE_SEARCH_JUNK = re.compile(r"[\s\-().]")


class ClientNotFound(LookupError):
    """The client id resolves to no row in this organization."""


class ClientService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.clients = ClientCRUD(session)

    @staticmethod
    def clauses(filters: SClientFilters) -> list:
        clauses = []
        if filters.phone is not None:
            clauses.append(
                Client.phone.contains(_PHONE_SEARCH_JUNK.sub("", filters.phone))
            )
        if filters.search is not None:
            clauses.append(
                or_(
                    Client.phone.icontains(_PHONE_SEARCH_JUNK.sub("", filters.search)),
                    Client.name.icontains(filters.search),
                )
            )
        if filters.status is not None:
            clauses.append(Client.status == filters.status)
        if filters.segment is not None:
            clauses.append(Client.segment == filters.segment)
        if filters.country is not None:
            clauses.append(Client.country == filters.country)
        if filters.language is not None:
            clauses.append(Client.language == filters.language)
        if filters.vip_status is not None:
            clauses.append(Client.vip_status == filters.vip_status)
        if filters.last_active_from is not None:
            clauses.append(Client.last_active >= filters.last_active_from)
        if filters.last_active_to is not None:
            clauses.append(Client.last_active <= filters.last_active_to)
        if filters.last_deposit_min is not None:
            clauses.append(Client.last_deposit >= filters.last_deposit_min)
        if filters.last_deposit_max is not None:
            clauses.append(Client.last_deposit <= filters.last_deposit_max)
        if filters.audience_id is not None:
            clauses.append(
                Client.id.in_(
                    select(AudienceMember.client_id).where(
                        AudienceMember.audience_id == filters.audience_id
                    )
                )
            )
        return clauses

    async def countries(self) -> list[str]:
        """Unique non-empty countries among existing clients."""
        return await self.clients.countries()

    async def page(self, filters: SClientFilters, limit: int, offset: int):
        """``([(client, audience_names, answered_calls)…], total)`` for one page."""
        clients, count = await self.clients.get_many_with_count(
            *self.clauses(filters),
            order_by=Client.id.desc(),
            limit=limit,
            offset=offset,
        )
        names_by_client = await AudienceMemberCRUD(
            self.session
        ).audience_names_by_client([c.id for c in clients])
        answered_by_client = await CallCRUD(self.session).answered_counts_by_client(
            [c.id for c in clients]
        )
        rows = [
            (c, names_by_client.get(c.id, []), answered_by_client.get(c.id, 0))
            for c in clients
        ]
        return rows, count

    async def get(self, client_id: int) -> tuple[Client, list[str], int]:
        """``(client, audience_names, answered_calls)``.

        Raises:
            ClientNotFound: If the client does not exist.
        """
        client = await self.clients.get_one_or_none(Client.id == client_id)
        if client is None:
            raise ClientNotFound(client_id)
        names = await AudienceMemberCRUD(self.session).audience_names_by_client(
            [client_id]
        )
        answered = await CallCRUD(self.session).answered_counts_by_client([client_id])
        return client, names.get(client_id, []), answered.get(client_id, 0)

    async def update(
        self, client_id: int, data: admin.SClientUpdate
    ) -> tuple[Client, list[str]]:
        """Apply the fields ``data`` sets; ``(client, audience_names)``.

        Raises:
            ClientNotFound: If the client does not exist.
        """
        client = await self.clients.get_one_or_none(Client.id == client_id)
        if client is None:
            raise ClientNotFound(client_id)
        values = data.model_dump(exclude_unset=True)
        if values:
            await self.clients.update(Client.id == client_id, data=values)
            self.session.expire(client)
            client = await self.clients.get_one_or_none(Client.id == client_id)
        names = await AudienceMemberCRUD(self.session).audience_names_by_client(
            [client_id]
        )
        return client, names.get(client_id, [])
