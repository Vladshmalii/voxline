"""Twilio Media Streams as a call leg.

The shape of a Twilio call, and where each piece lives:

1. **Webhook** — Twilio hits the org's voice URL; the controller answers with
   the TwiML from :meth:`TwilioTelephonyAdapter.answer_instructions`, which
   tells Twilio to open a bidirectional media stream to our WebSocket.
2. **Media handshake** — Twilio connects and sends ``connected`` then
   ``start`` events; the ``start`` carries the ``streamSid``/``callSid`` the
   serializer needs, which is why the transport cannot be built until
   :meth:`answer_media` has read them.
3. **Media** — 8 kHz µ-law, base64 in JSON envelopes, both directions.
   Pipecat's :class:`TwilioFrameSerializer` speaks that dialect and resamples
   to and from the pipeline's rates; nothing else in the stack knows µ-law
   exists.
4. **Control** — origination and hangup go through Twilio's REST API. The API
   root is :attr:`TelephonyConfig.control_url` when set (a Twilio-compatible
   double in tests, a region-pinned deployment in production), Twilio's cloud
   otherwise.

Auto hang-up: when credentials are configured, the serializer ends the Twilio
call on ``EndFrame``/``CancelFrame``, so a session's :meth:`hangup` drains and
the carrier leg actually dies. Without credentials the socket just closes and
Twilio tears the call down on its own timeout — degraded, and warned about
once at build time, not discovered from a stuck call.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Self
from xml.sax.saxutils import escape

import httpx
from fastapi import WebSocket
from loguru import logger
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

from src.application.engine.audio import ASR_SAMPLE_RATE
from src.common.enums.engine import TelephonyAdapterEnum
from src.integrations.telephony.base import (
    DEFAULT_HANDSHAKE_TIMEOUT_SECONDS,
    BaseTelephonyAdapter,
    TelephonyAdapters,
    TelephonyCapabilities,
    TelephonyConfig,
)
from src.integrations.telephony.websocket import PacedFastAPIWebsocketTransport

# Shared with the SMS route and the hooks service's signature check: one
# definition of how region/edge pinning becomes a hostname.
from src.utils.twilio import TWILIO_API_ROOT, api_root  # noqa: F401  (re-exported)

#: Remaining uncertainties in the contract above.
PROTOCOL_ASSUMPTIONS: tuple[str, ...] = (
    "the start event always precedes the first media event",
    "streamSid is stable for the life of the WebSocket",
)


class TwilioTelephonyAdapter(BaseTelephonyAdapter):
    """One Twilio Media Streams leg."""

    protocol_assumptions = PROTOCOL_ASSUMPTIONS

    capabilities: TelephonyCapabilities = TelephonyCapabilities(
        sample_rate=8000,
        encoding="ulaw",
        expects_start_event=True,
        supports_dial=True,
        supports_api_hangup=True,
        supports_dtmf=True,
    )

    @classmethod
    def from_config(cls, config: TelephonyConfig, *, call_id: str) -> Self:
        """Build a leg from an organization's telephony row.

        Recognised ``options``: ``region``/``edge`` (Twilio FQDN pinning),
        ``session_timeout`` (seconds of transport inactivity),
        ``handshake_timeout`` (seconds to wait for the start event),
        ``audio_in_sample_rate`` (pipeline input rate; defaults to the ASR
        rate so the recogniser gets audio it can use without a second
        resample), ``auto_hang_up`` (end the Twilio call on EndFrame; defaults
        to True when credentials are present).
        """
        return cls(config, call_id=call_id)

    def __init__(self, config: TelephonyConfig, *, call_id: str) -> None:
        """Initialise the adapter. No I/O happens here.

        Args:
            config: The organization's telephony row.
            call_id: Correlation id for logs.
        """
        self._config = config
        self._call_id = call_id
        options = config.options
        self._region: str | None = options.get("region")
        self._edge: str | None = options.get("edge")
        self._session_timeout: int | None = options.get("session_timeout")
        self._handshake_timeout: float = float(
            options.get("handshake_timeout", DEFAULT_HANDSHAKE_TIMEOUT_SECONDS)
        )
        self._audio_in_sample_rate: int = int(
            options.get("audio_in_sample_rate", ASR_SAMPLE_RATE)
        )

        has_credentials = bool(config.account_id and config.auth_token)
        self._auto_hang_up: bool = bool(options.get("auto_hang_up", has_credentials))
        if self._auto_hang_up and not has_credentials:
            # Fail toward a working call: the leg still runs, Twilio's own
            # timeout eventually reaps it, and the operator learns why now.
            logger.warning(
                f"call {call_id}: twilio auto_hang_up requested without "
                "account_id/auth_token; disabling it"
            )
            self._auto_hang_up = False

    # -- webhook -------------------------------------------------------------

    def answer_instructions(self, media_url: str) -> str:
        """TwiML that routes this call's media to `media_url`.

        Serve it as ``application/xml``. The same document answers an inbound
        webhook and scripts an outbound call (see :meth:`dial`).
        """
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Connect>"
            f'<Stream url="{escape(media_url, {'"': "&quot;"})}"/>'
            "</Connect></Response>"
        )

    # -- media ----------------------------------------------------------------

    async def answer_media(self, websocket: WebSocket) -> BaseTransport:
        """Read Twilio's opening events and build the transport.

        Args:
            websocket: The accepted media connection.

        Returns:
            A transport speaking Twilio's dialect through the serializer.

        Raises:
            TimeoutError: If the start event does not arrive in time.
        """
        start = await self._read_start_event(websocket)
        stream_sid: str = start["streamSid"]
        call_sid: str | None = start.get("callSid")
        logger.info(
            f"call {self._call_id}: twilio media started "
            f"(stream={stream_sid}, call={call_sid})"
        )

        serializer = TwilioFrameSerializer(
            stream_sid=stream_sid,
            call_sid=call_sid,
            account_sid=self._config.account_id,
            auth_token=self._config.auth_token,
            region=self._region,
            edge=self._edge,
            base_url=self._config.control_url,
            params=TwilioFrameSerializer.InputParams(
                twilio_sample_rate=self.capabilities.sample_rate,
                auto_hang_up=self._auto_hang_up and call_sid is not None,
            ),
        )
        return PacedFastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=self._audio_in_sample_rate,
                add_wav_header=False,
                serializer=serializer,
                session_timeout=self._session_timeout,
            ),
        )

    async def _read_start_event(self, websocket: WebSocket) -> dict[str, Any]:
        """Consume events until Twilio's ``start`` arrives, and return it."""
        async with asyncio.timeout(self._handshake_timeout):
            while True:
                message = json.loads(await websocket.receive_text())
                event = message.get("event")
                if event == "start":
                    return message["start"]
                if event == "connected":
                    continue
                logger.debug(
                    f"call {self._call_id}: ignoring twilio {event!r} before start"
                )

    # -- control --------------------------------------------------------------

    async def dial(
        self,
        *,
        to: str,
        media_url: str,
        caller_id: str | None = None,
        status_url: str | None = None,
    ) -> str:
        """Originate an outbound Twilio call whose media streams to `media_url`.

        Args:
            to: Destination number, E.164.
            media_url: Public WebSocket URL for the media stream.
            caller_id: Overrides the config's default caller id.
            status_url: Twilio status callback for terminal dispositions.

        Returns:
            The new call's SID.

        Raises:
            ValueError: If credentials or a caller id are missing.
            httpx.HTTPStatusError: If Twilio rejects the request.
        """
        account_id, auth_token = self._require_credentials("dial")
        from_number = caller_id or self._config.caller_id
        if not from_number:
            raise ValueError("twilio dial needs a caller_id (config or per-call)")

        data = {
            "To": to,
            "From": from_number,
            "Twiml": self.answer_instructions(media_url),
        }
        if status_url:
            data["StatusCallback"] = status_url
            # Only terminal events: provisional ones (ringing…) are not recorded.
            data["StatusCallbackEvent"] = "completed"

        async with httpx.AsyncClient(auth=(account_id, auth_token)) as client:
            response = await client.post(
                f"{self._api_root()}/2010-04-01/Accounts/{account_id}/Calls.json",
                data=data,
            )
            if response.status_code >= 400:
                logger.error(
                    f"call {self._call_id}: twilio dial to {to} rejected "
                    f"({response.status_code}): {response.text}"
                )
            response.raise_for_status()
            call_sid = response.json()["sid"]
        logger.info(f"call {self._call_id}: twilio dialled {to} (call={call_sid})")
        return call_sid

    async def hangup(self, call_ref: str) -> None:
        """End a Twilio call by setting its status to completed.

        Args:
            call_ref: The call SID.
        """
        account_id, auth_token = self._require_credentials("hangup")
        async with httpx.AsyncClient(auth=(account_id, auth_token)) as client:
            response = await client.post(
                f"{self._api_root()}/2010-04-01/Accounts/{account_id}/Calls/{call_ref}.json",
                data={"Status": "completed"},
            )
            # 404 means the far end already hung up — the outcome we wanted.
            if response.status_code != 404:
                response.raise_for_status()

    def _api_root(self) -> str:
        return api_root(self._config.control_url, region=self._region, edge=self._edge)

    def _require_credentials(self, action: str) -> tuple[str, str]:
        if not (self._config.account_id and self._config.auth_token):
            raise ValueError(f"twilio {action} needs account_id and auth_token")
        return self._config.account_id, self._config.auth_token


TelephonyAdapters[TelephonyAdapterEnum.twilio] = TwilioTelephonyAdapter
