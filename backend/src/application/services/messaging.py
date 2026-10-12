"""Sending one SMS: persist, resolve the route, hand it over, record the verdict.

Unlike originating a call, a send is short enough to do in the request path —
there is no long-lived stateful process to hand to a worker, and an API caller
who asks to text a customer wants the provider's verdict now, not a task id.

The row is written **before** the provider is called, for the same reason the
dialer registers a call before dialing: the delivery callback can arrive
before our own HTTP response does, and a callback with no row to update is a
verdict thrown away. The row is therefore also what a failed send leaves
behind — ``failed`` with the vendor's words in ``error``, not a 400 and no
trace.

What arrives later (``delivered``, ``undelivered``) reaches the hooks service
(``src/controller_hooks/api/v1/sms.py``), which records it through
:meth:`MessagingService.record_callback`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.billing import BillingService
from src.application.worker import registry
from src.common.enums.engine import MessageStatusEnum
from src.integrations.messaging import build_messaging
from src.models.messaging import Message, Messaging
from src.repositories.billing import OrganizationBalanceCRUD
from src.repositories.call import SMS_SENT_STATUSES, mark_sms_sent
from src.repositories.messaging import MessageCRUD, MessagingCRUD
from src.schemas.admin import SSmsSend
from src.settings import SETTINGS
from src.utils.phone import normalize_phone
from src.utils.tokens import mint
from src.utils.url import status_callback_url

#: Statuses that end a message's life and stamp ``settled_at``. Ours, not a
#: vendor's — which dispositions are terminal is a question about our own
#: bookkeeping, and every adapter has already translated into these.
_TERMINAL = frozenset(
    {
        MessageStatusEnum.delivered,
        MessageStatusEnum.undelivered,
        MessageStatusEnum.failed,
        MessageStatusEnum.canceled,
    }
)


class SendError(ValueError):
    """The message cannot be sent; the text says why."""


class UnknownMessage(LookupError):
    """No message has this uuid, or the messaging row that sent it is gone."""


class RouteUnusable(ValueError):
    """The messaging row that sent this message no longer builds an adapter."""


class CallbackNotVerified(ValueError):
    """The delivery callback failed its provider's authenticity check."""


class MessagingService:
    def __init__(self, session: AsyncSession, org_uuid: str) -> None:
        self.session = session
        #: Carried so a delivery callback landing on any hooks replica can
        #: find this message's database without a fan-out over every org.
        self.org_uuid = org_uuid

    async def send_sms(self, data: SSmsSend, *, call_id: int | None = None) -> Message:
        """Send one SMS through the organization's messaging route.

        Args:
            data: Destination, body, and optionally which route and sender.
            call_id: The call this send was triggered from (the in-call
                "send_sms" tool), when there is one. Recorded on the message
                so stats can join "was a call followed by an SMS" — see
                ``Message.call_id``. None for sends with no call context
                (e.g. a manual/API send).

        Returns:
            The message row: ``sent`` with a ``provider_ref`` when the
            provider accepted it, ``failed`` with an ``error`` when it did not.

        Raises:
            SendError: If the message never reached the provider at all — an
                undialable number, no usable route, missing credentials. These
                are refusals, not attempts, and leave no row.
        """
        try:
            to_number = normalize_phone(data.to)
        except ValueError as exc:
            raise SendError(str(exc)) from exc

        row = await self._route(data.messaging_id)
        if not await OrganizationBalanceCRUD(self.session).has_funds("sms"):
            raise SendError("insufficient SMS balance")
        try:
            adapter = build_messaging(MessagingCRUD.build_config(row))
        except (KeyError, ValueError) as exc:
            # An unknown adapter string or a config that no longer validates:
            # the row names itself so the operator knows which one to fix.
            raise SendError(f"messaging row {row.id} is not usable: {exc}") from exc

        if adapter.protocol_assumptions:
            logger.debug(
                f"messaging {row.adapter}: assuming {'; '.join(adapter.protocol_assumptions)}"
            )

        messages = MessageCRUD(self.session)
        message = await messages.create(
            {
                "messaging_id": row.id,
                "call_id": call_id,
                "to_number": to_number,
                "sender": data.sender or row.sender or row.sender_pool_id,
                "body": data.body,
                "segments": adapter.segments(data.body),
                "status": MessageStatusEnum.queued,
            }
        )
        # Committed before the send: a delivery callback can beat our own
        # response, and it must find a row to update — and know where it lives.
        await self.session.commit()
        message_uuid = str(message.uuid)
        await registry.register_message(message_uuid, org_uuid=self.org_uuid)

        status_url = (
            self._status_url(row, message_uuid)
            if adapter.capabilities.supports_delivery_status
            else None
        )

        try:
            provider_ref = await adapter.send(
                to=to_number, body=data.body, sender=data.sender, status_url=status_url
            )
        except ValueError as exc:  # missing credentials or sender
            await self._fail(message.id, str(exc))
            raise SendError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            # The vendor's own words are the useful part: "unverified number",
            # "unreachable destination", "blocked as spam" are all operator
            # problems, and a bare 400 tells nobody which.
            reason = (
                f"{row.adapter} refused the message ({exc.response.status_code}): "
                f"{exc.response.text[:500]}"
            )
            await self._fail(message.id, reason)
            raise SendError(reason) from exc
        except httpx.HTTPError as exc:  # timeout, DNS, connection reset
            # Deliberately *not* failed: a timeout on a POST that may have
            # been accepted is unknown, not refused. It stays queued until a
            # callback settles it or an operator reconciles by provider_ref.
            reason = f"{row.adapter} unreachable: {exc}"
            await MessageCRUD(self.session).update(
                Message.id == message.id, data={"error": reason[:2000]}
            )
            await self.session.commit()
            raise SendError(reason) from exc

        await messages.advance(
            Message.id == message.id,
            status=MessageStatusEnum.sent,
            data={"provider_ref": provider_ref, "sent_at": datetime.now()},
        )
        await BillingService(self.session).charge_sms(message.id)
        if call_id is not None:
            # VOAD-80: the SMS is the call's result. Usually a no-op here (the
            # call is still live); it matters for a late send on a settled call.
            await mark_sms_sent(self.session, call_id)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def record_callback(
        self,
        message_uuid: str,
        *,
        token: str | None,
        headers: Mapping[str, str],
        form: dict[str, str] | None,
        payload: Any,
    ) -> None:
        """Record a provider's delivery verdict for one message, and commit.

        The verdict may only move the message forward (``MessageCRUD.advance``);
        a provisional one, or a batch with nothing about this message, writes
        nothing.

        Args:
            message_uuid: The message the callback URL names.
            token: The URL's HMAC token, as received.
            headers: The request headers (a signature rides in them).
            form: The form body when the provider posted one — what a
                signature covers — else None.
            payload: The parsed body, JSON or form.

        Raises:
            UnknownMessage: If the message or its messaging row is gone.
            RouteUnusable: If that row no longer builds an adapter.
            CallbackNotVerified: If the callback is not provably the provider's.
        """
        found = await MessageCRUD(self.session).with_route(message_uuid)
        if found is None:
            raise UnknownMessage(message_uuid)
        message, route = found

        try:
            adapter = build_messaging(MessagingCRUD.build_config(route))
        except (KeyError, ValueError) as exc:
            logger.error(f"message {message_uuid}: messaging row {route.id}: {exc}")
            raise RouteUnusable(str(exc)) from exc

        # Before the verdict is believed, let alone written.
        if not adapter.verify_callback(
            url=self._callback_url(route, message_uuid, token),
            headers=headers,
            form=form,
        ):
            logger.warning(f"message {message_uuid}: callback failed verification")
            raise CallbackNotVerified(message_uuid)

        verdict = adapter.parse_callback(payload, provider_ref=message.provider_ref)
        if verdict.status is None:
            return  # provisional, or a batch with nothing about this message

        data: dict = {}
        if verdict.status in _TERMINAL:
            data["settled_at"] = datetime.now()
        if verdict.error:
            data["error"] = verdict.error[:2000]

        advanced = await MessageCRUD(self.session).advance(
            Message.uuid == message_uuid, status=verdict.status, data=data
        )
        if (
            advanced
            and message.call_id is not None
            and verdict.status in SMS_SENT_STATUSES
        ):
            # VOAD-80: a late sent/delivered verdict corrects a call that
            # already settled with another outcome.
            await mark_sms_sent(self.session, message.call_id)
        await self.session.commit()

        if not advanced:
            logger.debug(
                f"message {message_uuid}: {verdict.status} callback ignored, "
                "the row is already further along"
            )

    async def _fail(self, message_id: int, reason: str) -> None:
        """Record a refusal the provider was explicit about."""
        await MessageCRUD(self.session).advance(
            Message.id == message_id,
            status=MessageStatusEnum.failed,
            data={"error": reason[:2000], "settled_at": datetime.now()},
        )
        await self.session.commit()

    def _status_url(self, row: Messaging, message_uuid: str) -> str | None:
        """Where the provider should report this message's delivery.

        The base is the hooks service's public URL — the same one the call
        worker hands carriers for media, unless the messaging row names its
        own. Without either, the message is sent with no callback rather than
        refused: a delivered SMS with an unknown verdict beats no SMS.
        """
        worker = SETTINGS.call_worker
        base = row.options.get("status_url_base") or (
            worker.media_url if worker else None
        )
        if not base:
            logger.warning(
                f"messaging row {row.id}: no status_url_base and no CALL_WORKER__MEDIA_URL; "
                "sending without a delivery callback"
            )
            return None
        return status_callback_url(
            base, message_uuid, mint(SETTINGS.secret_key, message_uuid)
        )

    @staticmethod
    def _callback_url(
        route: Messaging, message_uuid: str, token: str | None
    ) -> str | None:
        """This message's status URL as the provider was handed it.

        Rebuilt rather than read off the request: behind an ingress ``request.url``
        is the internal address, which the provider never saw and never signed.
        None when no public base is configured — an adapter that needs to verify a
        signature treats that as a failure, which is the fail-closed half of this.
        """
        worker = SETTINGS.call_worker
        base = route.options.get("status_url_base") or (
            worker.media_url if worker else None
        )
        if not base:
            return None
        return status_callback_url(base, message_uuid, token or "")

    async def _route(self, messaging_id: int | None) -> Messaging:
        """The messaging row to send through — named, or the active one."""
        repo = MessagingCRUD(self.session)
        if messaging_id is not None:
            row = await repo.get_one_or_none(Messaging.id == messaging_id)
            if row is None:
                raise SendError(f"messaging route {messaging_id} not found")
            if not row.is_active:
                raise SendError(f"messaging route {messaging_id} is not active")
            return row

        active = await repo.get_many_ordered(Messaging.is_active.is_(True), limit=2)
        if not active:
            raise SendError("no active messaging route is configured")
        if len(active) > 1:
            # Two active routes and no id is genuinely ambiguous; picking one
            # silently would send from whichever number sorted first.
            raise SendError(
                "several active messaging routes; name one with messaging_id"
            )
        return active[0]
