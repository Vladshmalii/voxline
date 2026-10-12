"""Delivery callbacks for messages this service sent.

The same trust boundary as the media surface, and the same two locks:

* the URL carries an HMAC of the message uuid, so any hooks replica can
  authenticate the request without a lookup;
* a provider that signs its webhooks is held to that signature — required,
  not merely checked when present, because an optional check is one an
  attacker skips.

And the same write discipline: a disposition may only move a message
**forward** (``MessageCRUD.advance``). Carriers report out of order, retry
freely, and deliver duplicates; none of that may overwrite a verdict with a
staler one.

The org the message belongs to is not in the URL, so the sender writes it to
Redis before handing the message over — the same handoff the dialer makes for
a call, with a TTL wide enough to outlast a carrier's own validity period.
When that entry lapses the callback 404s and the row keeps the status it had:
a stale verdict is worse than a missing one.

**No vendor is named here.** Providers disagree about everything a callback is
made of — Twilio posts a form and signs it, Mamonty posts a JSON *list* and
signs nothing, and their status vocabularies do not overlap. All of that lives
behind :meth:`BaseMessagingAdapter.verify_callback` and
:meth:`~BaseMessagingAdapter.parse_callback`, so this router reads one shape:
is it authentic, and what does it say. A third provider is an adapter, not a
branch below.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.application.services.messaging import (
    CallbackNotVerified,
    MessagingService,
    RouteUnusable,
    UnknownMessage,
)
from src.application.worker import registry
from src.core.db.session import SessionMaker
from src.settings import SETTINGS
from src.utils.tokens import verify

router = APIRouter()


@router.post("/sms/{message_uuid}/status", status_code=204)
async def message_status(
    request: Request, message_uuid: str, t: str | None = None
) -> None:
    """Record a provider's delivery verdict for one message."""
    if not verify(SETTINGS.secret_key, message_uuid, t):
        raise HTTPException(status_code=403, detail="bad token")

    # Some providers post form-encoded, some JSON (and some JSON that is a
    # list). The form is kept separately because a signature covers it.
    form: dict[str, str] | None = None
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - not JSON, try the form shape
        form = {key: str(value) for key, value in (await request.form()).items()}
        payload = form

    org_uuid = await registry.message_route(message_uuid)
    if org_uuid is None:
        raise HTTPException(status_code=404, detail="unknown message")

    async with SessionMaker.get_session(org_uuid)() as session:
        try:
            await MessagingService(session, org_uuid).record_callback(
                message_uuid,
                token=t,
                headers=request.headers,
                form=form,
                payload=payload,
            )
        except UnknownMessage:
            raise HTTPException(status_code=404, detail="unknown message")
        except RouteUnusable as exc:
            # The row that sent this message no longer builds. A 500 is right:
            # the verdict is real and the provider should retry it once an
            # operator has fixed the row, rather than have it dropped here.
            raise HTTPException(
                status_code=500, detail="messaging route unusable"
            ) from exc
        except CallbackNotVerified:
            raise HTTPException(status_code=403, detail="callback not verified")
