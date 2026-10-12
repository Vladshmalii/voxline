"""The telephony-facing surface: media sockets in, status webhooks in.

This is the one part of the platform a telephony provider connects *to*, so
it holds the trust boundary:

* Every route is addressed by call uuid and authenticated by the HMAC token
  the dispatcher minted into the URL at dial time — stateless to verify, so
  any hooks process can answer for any call.
* A carrier that signs its webhooks is additionally held to that signature.
  The URL token stops an attacker who never saw a real URL; Twilio's
  ``X-Twilio-Signature`` also covers the parameters, so a captured URL
  replayed with a rewritten ``CallStatus`` fails. It is required, not merely
  checked when present, for any leg whose trunk is Twilio — an optional
  signature check is one an attacker skips.
* The media socket is additionally single-use: the registry's atomic claim
  admits the first valid connection and refuses every later one. Providers
  never reconnect a media stream mid-call, so "already claimed" always means
  replay or duplicate, never a legitimate retry.
* The hooks lifespan preloads the pipeline stack (``runner`` → engine →
  pipecat). A call pipeline is built only after a socket passes both checks.

Close codes: 4403 bad token, 4409 already claimed / nothing pending,
4404 call no longer runnable (canceled or swept while connecting).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, WebSocket
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.worker import dispatch, registry
from src.application.worker.dispositions import classify, extract
from src.common.enums.engine import CallStatusEnum, TelephonyAdapterEnum
from src.core.db.session import SessionMaker
from src.models.agent import VoiceAgent
from src.models.call import Call, CallAttempt
from src.models.telephony import Telephony
from src.repositories.call import CallAttemptCRUD
from src.settings import SETTINGS
from src.utils.twilio import verify_signature

router = APIRouter()

#: Wire default for a leg whose telephony row has no ``capabilities.sample_rate``
#: override — matches every adapter's own default (8 kHz telephony audio).
_DEFAULT_SAMPLE_RATE = 8000


@router.post("/media/{call_uuid}/answer")
async def jambonz_answer(call_uuid: str, t: str | None = None) -> list[dict]:
    """jambonz's ``call_hook``: the verb array that starts this leg's audio.

    Unlike Twilio, jambonz has no inline-instructions parameter on its dial
    API — it always answers a call by fetching a webhook. This is that
    webhook, fired once when jambonz is ready to run the call, separate from
    (and before) the ``listen`` verb's WebSocket connecting to `/media`.

    The media URL is not looked up anywhere: it is re-derived from the same
    ``(secret, media_base, call_uuid)`` triple ``registry.call_urls`` used to
    hand it to jambonz in the first place, so there is exactly one place this
    string is computed, per the module's own rule for the status URL.
    """
    if not registry.verify_token(SETTINGS.secret_key, call_uuid, t):
        raise HTTPException(status_code=403, detail="bad token")

    route = await registry.route(call_uuid)
    if route is None:
        raise HTTPException(status_code=404, detail="unknown call")

    async with SessionMaker.get_session(route["org_uuid"])() as session:
        carrier = (
            (
                await session.execute(
                    select(Telephony.options, Telephony.capabilities)
                    .select_from(CallAttempt)
                    .join(Call, Call.id == CallAttempt.call_id)
                    .join(VoiceAgent, VoiceAgent.id == Call.agent_id)
                    .join(Telephony, Telephony.id == VoiceAgent.telephony_id)
                    .where(CallAttempt.id == route["call_id"])
                )
            )
            .mappings()
            .one_or_none()
        )
    if carrier is None:
        raise HTTPException(status_code=404, detail="unknown call")

    worker = SETTINGS.call_worker
    media_base = carrier["options"].get("media_url_base") or (
        worker.media_url if worker else None
    )
    if not media_base:
        logger.error(f"answer webhook for {call_uuid}: no media_url_base configured")
        raise HTTPException(status_code=500, detail="media base not configured")

    media_url, _ = registry.call_urls(SETTINGS.secret_key, media_base, call_uuid)
    sample_rate = carrier["capabilities"].get("sample_rate", _DEFAULT_SAMPLE_RATE)
    return [
        {"verb": "answer"},
        {
            "verb": "listen",
            "url": media_url,
            "mixType": "mono",
            "sampleRate": sample_rate,
            # jambonz's mod_audio_fork has two bidirectional-audio modes:
            # plain "enabled" (file-based play/killAudio events, the
            # default) and "streaming" (raw PCM piped straight into the
            # RTP leg). Without this, everything we send back over the
            # media socket is silently accepted and never played — the
            # agent's TTS never reaches the caller.
            "bidirectionalAudio": {
                "enabled": True,
                "streaming": True,
                "sampleRate": sample_rate,
            },
        },
    ]


@router.websocket("/media/{call_uuid}")
async def media_socket(websocket: WebSocket, call_uuid: str) -> None:
    """Accept a provider's media stream and run the call it belongs to."""
    if not registry.verify_token(
        SETTINGS.secret_key, call_uuid, websocket.query_params.get("t")
    ):
        await websocket.close(code=4403)
        return

    pending = await registry.claim(call_uuid)
    if pending is None:
        logger.warning(
            f"media socket for {call_uuid}: nothing pending (replay or expired)"
        )
        await websocket.close(code=4409)
        return

    await websocket.accept()
    logger.info(f"media socket for {call_uuid}: accepted, handing off to engine")
    # Preloaded by the hooks lifespan; keep the route module itself lightweight.
    from src.application.worker import runner

    await runner.run_media_call(
        websocket, org_uuid=pending["org_uuid"], call_id=pending["call_id"]
    )


@router.post("/media/{call_uuid}/status", status_code=204)
async def call_status(request: Request, call_uuid: str, t: str | None = None) -> None:
    """Record a provider's disposition for a call (busy, no answer, …).

    Guarded like every other status write: only a call still in flight can be
    disposed, so a late or duplicate webhook cannot rewrite history.
    """
    if not registry.verify_token(SETTINGS.secret_key, call_uuid, t):
        raise HTTPException(status_code=403, detail="bad token")

    route = await registry.route(call_uuid)
    if route is None:
        raise HTTPException(status_code=404, detail="unknown call")

    # jambonz posts JSON, Twilio posts form-encoded; both name a status field.
    form: dict[str, str] | None = None
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - not JSON, try the form shape
        form = {key: str(value) for key, value in (await request.form()).items()}
        payload = form
    if not isinstance(payload, dict):
        payload = {}
    parsed = extract(payload)

    # The registry's call_id is the attempt id — legs are what webhooks address.
    async with SessionMaker.get_session(route["org_uuid"])() as session:
        # Before anything is believed, let alone written: the trunk decides
        # what proof this webhook owes. Signature verification precedes the
        # provisional-status shortcut so an unsigned Twilio POST is refused,
        # not quietly accepted because it happened to say "ringing".
        await _verify_carrier_signature(
            session, request, call_uuid, t, form, route["call_id"]
        )

        attempt_id = route["call_id"]
        provider_ref = await session.scalar(
            select(CallAttempt.provider_ref).where(CallAttempt.id == attempt_id)
        )
        logger.info(
            f"status webhook: attempt {attempt_id} provider_ref={provider_ref} "
            f"payload={dict(payload)}"
        )

        disposition = classify(parsed)
        if disposition is None:
            return  # provisional statuses (ringing…) are not ours to record
        if disposition.unknown:
            logger.warning(
                f"status webhook: attempt {attempt_id} provider_ref={provider_ref}: "
                f"unknown provider status {parsed.status!r}"
            )

        data: dict = {
            "status": disposition.status,
            "provider_status": parsed.status[:100],
            "provider_reason": parsed.reason_text,
        }
        if disposition.error:
            data["error"] = disposition.error
        await CallAttemptCRUD(session).update(
            CallAttempt.id == attempt_id,
            CallAttempt.status.in_(
                (CallStatusEnum.dialing, CallStatusEnum.in_progress)
            ),
            data=data,
        )
        await session.commit()

        # Fold a finished attempt into its parent call now instead of waiting
        # for the next minute's dispatcher tick (the UI would otherwise show the
        # attempt as terminal while the call still reads "calling").
        # ``completed`` is skipped: it waits for analysis anyway. Best effort —
        # the tick remains the safety net.
        if disposition.status != CallStatusEnum.completed:
            try:
                call_id = await session.scalar(
                    select(CallAttempt.call_id).where(CallAttempt.id == attempt_id)
                )
                if call_id is not None:
                    await dispatch.settle_calls(session, call_ids=[call_id])
                    await session.commit()
            except Exception as exc:  # noqa: BLE001 - the tick will settle it
                logger.warning(
                    f"status webhook: attempt {attempt_id}: immediate settle failed: {exc}"
                )


async def _verify_carrier_signature(
    session: AsyncSession,
    request: Request,
    call_uuid: str,
    token: str | None,
    form: dict[str, str] | None,
    attempt_id: int,
) -> None:
    """Hold a signing carrier to its signature, or refuse the webhook.

    Only Twilio legs are held to one: the SIP bridge signs nothing and reaches
    this service over the VPC, so demanding a signature there would break
    every disposition it reports.

    The signed string is the status URL *as the dialer handed it out*,
    rebuilt through ``registry.call_urls`` rather than read off the request —
    behind an ingress, ``request.url`` is the internal address, which Twilio
    never saw and never signed.

    Raises:
        HTTPException: 403 when a Twilio leg's signature is absent, wrong, or
            unverifiable because the media base is not configured.
    """
    carrier = (
        (
            await session.execute(
                select(Telephony.adapter, Telephony.auth_token, Telephony.options)
                .select_from(CallAttempt)
                .join(Call, Call.id == CallAttempt.call_id)
                .join(VoiceAgent, VoiceAgent.id == Call.agent_id)
                .join(Telephony, Telephony.id == VoiceAgent.telephony_id)
                .where(CallAttempt.id == attempt_id)
            )
        )
        .mappings()
        .one_or_none()
    )

    if carrier is None or carrier["adapter"] != TelephonyAdapterEnum.twilio:
        return

    worker = SETTINGS.call_worker
    media_base = carrier["options"].get("media_url_base") or (
        worker.media_url if worker else None
    )
    if not media_base:
        # Fail closed: a check that cannot run is not a check that passed.
        logger.error(
            f"status webhook for {call_uuid}: cannot verify the twilio signature, "
            "no media_url_base on the telephony row and no CALL_WORKER__MEDIA_URL"
        )
        raise HTTPException(status_code=403, detail="signature unverifiable")

    _, status_url = registry.call_urls(SETTINGS.secret_key, media_base, call_uuid)
    if not verify_signature(
        carrier["auth_token"] or "",
        status_url,
        form,
        request.headers.get("X-Twilio-Signature"),
    ):
        logger.warning(f"status webhook for {call_uuid}: bad twilio signature")
        raise HTTPException(status_code=403, detail="bad twilio signature")
