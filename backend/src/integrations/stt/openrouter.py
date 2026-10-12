"""OpenRouter transcription: one key in front of every ASR the aggregator resells.

The point of this adapter is reach, not protocol. An organization that binds
``openrouter`` gets ``openai/whisper-large-v3``, ``google/chirp-3`` and the rest
of the transcription catalogue by editing ``model.code`` in one row — no key per
vendor, no adapter per vendor. What it pays for that is the shape of the wire,
which is the opposite of every other recogniser in this package.

========================  TRANSPORT CONTRACT  ========================

``POST {root}/audio/transcriptions``, JSON in and JSON out. **Not a WebSocket,
and not OpenAI-compatible despite the path** — OpenAI's endpoint takes
``multipart/form-data`` with a ``file`` part; this one takes base64 audio under
``input_audio``, so pointing an OpenAI client at it sends the wrong shape::

    {"model": "openai/whisper-large-v3",
     "input_audio": {"data": "<base64>", "format": "wav"},
     "language": "en"}

    → {"text": "...", "usage": {"seconds": 9.2, "cost": 0.000508}}

``data`` is bare base64, never a ``data:`` URI, and ``format`` must match the
bytes actually sent.

What that costs
---------------
**Nothing arrives while the caller is still speaking.** A request is one
complete utterance and the transcript comes back whole, so there are no
partials, no stable prefix, and nothing for speculative work downstream to feed
on. This is the Voxtral position, one step further: there the transcript at
least arrived over a socket that was already open.

Segmentation therefore comes from Pipecat's :class:`SegmentedSTTService`, which
buffers VAD-gated audio and hands over a WAV when the caller stops. Note what
that means for the turn cascade: the segment boundary is the *VAD* stop, not the
turn commit. When the turn analyzer rejects a pause as mid-utterance, the caller's
one sentence becomes two requests and two transcripts — which is why
:meth:`~src.integrations.stt.base.BaseSttAdapter.flush` joins the finals rather
than returning the last one. Two short uploads also cost more than one, on an
API billed by the second of audio.

Latency is a round trip after the caller stops talking, against a vendor
OpenRouter chose. :data:`DEFAULT_TIMEOUT_SECONDS` bounds it: past that the turn
commits with whatever it has instead of holding the call open on a slow
provider. The turn controller's ceiling fires regardless, so a timeout degrades
the turn rather than hanging it.

Language
--------
``language`` is a real ISO-639-1 parameter here, not a hint that is quietly
dropped, so ``accepts_language_hint`` is true. Detection is the other way round:
the plain ``json`` response carries no language at all, and the ``verbose_json``
that does is documented as OpenAI-compatible providers only. So
``reports_language`` is false by default and the field is read when a provider
happens to send it.

Both halves of that were checked against a live account rather than assumed.
Default ``json`` on ``openai/whisper-large-v3``: transcript, no language.
The same audio with ``provider.options["body"] = {"response_format":
"verbose_json"}``: ``language: "en"`` alongside the transcript. So turning the
capability on is two row edits — the body option that makes the vendor send it,
and ``capabilities.reports_language`` that makes the switcher believe it — and
an organization whose slug routes elsewhere should verify the first before
setting the second.

=====================================================================
"""

from __future__ import annotations

import base64
from collections.abc import AsyncGenerator
from typing import Any, Final

import httpx
from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

from src.application.engine.audio import ASR_SAMPLE_RATE, AudioPath
from src.application.engine.capabilities import SttCapabilities
from src.application.engine.config import SttConfig
from src.common.enums.engine import SttAdapterEnum
from src.integrations.stt.base import BaseSttAdapter, SttAdapters, UtteranceBuffer
from src.utils.openrouter import api_root, headers

#: What this client assumes that the contract above does not settle. Logged per
#: call from the recogniser actually selected.
PROTOCOL_ASSUMPTIONS: Final[tuple[str, ...]] = (
    "segments are cut at VAD stops, so one caller turn may become several requests",
    "no language is reported unless the row asks for verbose_json and the vendor honours it",
    "a transcription slower than the timeout is dropped, not retried",
)

#: Route under the API root. Its own constant because the readiness probe has to
#: reach the same host without importing this module (it pulls in pipecat).
TRANSCRIPTIONS_ROUTE: Final[str] = "/audio/transcriptions"

#: Container the segment is uploaded in. ``SegmentedSTTService`` wraps the
#: buffer in WAV for exactly this kind of upload API.
AUDIO_FORMAT: Final[str] = "wav"

#: Ceiling on one transcription request. Generous against a cold vendor, short
#: enough that the turn does not wait on a provider that has stopped answering.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0

#: Model used when a row leaves ``code`` empty. Named in full, as OpenRouter
#: requires — a bare ``whisper-large-v3`` is rejected as a model that does not exist.
DEFAULT_STT_MODEL: Final[str] = "openai/whisper-large-v3"


class OpenRouterSTTAdapter(BaseSttAdapter, SegmentedSTTService):
    """Batch transcription through OpenRouter's aggregated ASR catalogue.

    Both bases are load-bearing: ``BaseSttAdapter`` is the registry contract,
    and ``SegmentedSTTService`` is what turns a continuous audio stream into the
    discrete utterances this API accepts.
    """

    protocol_assumptions: tuple[str, ...] = PROTOCOL_ASSUMPTIONS

    #: Read off OpenRouter's documented contract, not measured against traffic —
    #: and the values that matter follow from the endpoint being batch rather
    #: than from any one vendor behind it.
    #:
    #: ``min_commit_seconds`` and ``tail_silence_seconds`` are zero because
    #: neither is a thing here: an upload of any length is a valid request, and
    #: there is no open buffer for trailing silence to flush.
    capabilities: SttCapabilities = SttCapabilities(
        streams_during_speech=False,
        emits_completion_event=False,
        min_commit_seconds=0.0,
        tail_silence_seconds=0.0,
        reports_language=False,
        sample_rate=ASR_SAMPLE_RATE,
        accepts_language_hint=True,
    )

    @classmethod
    def from_config(
        cls, config: SttConfig, *, call_id: str, audio_path: AudioPath
    ) -> OpenRouterSTTAdapter:
        """Build a client from an organization's STT row.

        ``audio_path`` is accepted for the contract and unused: this adapter
        never resamples, because ``SegmentedSTTService`` writes its WAV at the
        pipeline's own rate and the endpoint reads the rate out of the header.
        """
        provider = config.model.provider
        if not provider.api_key:
            logger.warning(
                "openrouter stt: no api_key on the provider row; "
                "every transcription will come back 401"
            )
        options = provider.options
        return cls(
            url=f"{api_root(provider.url)}{TRANSCRIPTIONS_ROUTE}",
            request_headers=headers(provider.api_key, options),
            model=config.model.code or DEFAULT_STT_MODEL,
            language=config.language or "en",
            timeout=float(options.get("timeout", DEFAULT_TIMEOUT_SECONDS)),
            # Everything else the endpoint takes — temperature, response_format,
            # a `provider` routing block, per-vendor passthrough — is a row edit
            # rather than a parameter here. See the package Readme.
            body=dict(options.get("body", {})),
        )

    def __init__(
        self,
        *,
        url: str,
        request_headers: dict[str, str],
        model: str = DEFAULT_STT_MODEL,
        language: str | Language = Language.EN,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        body: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the client.

        Args:
            url: Full transcription endpoint.
            request_headers: Authorization and attribution, from
                :func:`src.utils.openrouter.headers`.
            model: OpenRouter model slug, vendor prefix included.
            language: Language sent with each request. ISO-639-1 is what the
                endpoint documents, so a regional tag is cut to its base subtag.
            timeout: Ceiling on one request, in seconds.
            body: Extra request fields, merged under everything this class sets.
            **kwargs: Passed to :class:`SegmentedSTTService`.
        """
        # `settings` is the base class's store for model and language, and it is
        # also what makes `STTUpdateSettingsFrame` work — the language switcher
        # sends one per call, and a private copy would never see it.
        super().__init__(settings=STTSettings(model=model, language=language), **kwargs)
        self._url = url
        self._headers = request_headers
        self._timeout = timeout
        self._body = body or {}
        self._http: httpx.AsyncClient | None = None
        self._utterance = UtteranceBuffer()
        self._detected_language: str | None = None

    # -- public surface ----------------------------------------------------

    def flush(self) -> str:
        """Return the transcript accumulated for the current turn and clear it.

        Joins every segment, not just the last: a caller whose pause the turn
        analyzer rejected as mid-utterance has been transcribed in pieces, and
        the turn is made of all of them.
        """
        text = self._utterance.text()
        self._utterance.clear()
        return text

    @property
    def detected_language(self) -> str | None:
        """Language the vendor reported, when one reports at all.

        Only populated when the row asks for ``verbose_json`` *and* the vendor
        behind the slug honours it; see the module docstring. The value is
        normalised to the lowercase code the engine speaks.
        """
        return self._detected_language

    # -- lifecycle ---------------------------------------------------------

    async def start(self, frame: StartFrame) -> None:
        """Open the HTTP client when the pipeline starts."""
        await super().start(frame)
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)

    async def stop(self, frame: EndFrame) -> None:
        """Close the HTTP client on a graceful end."""
        await super().stop(frame)
        await self._close()

    async def cancel(self, frame: CancelFrame) -> None:
        """Close the HTTP client immediately."""
        await super().cancel(frame)
        await self._close()

    async def cleanup(self) -> None:
        """Release the HTTP client at teardown."""
        await super().cleanup()
        await self._close()

    async def _close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # -- transcription -----------------------------------------------------

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None]:
        """Transcribe one VAD-delimited segment.

        Args:
            audio: The segment as a WAV container, from ``SegmentedSTTService``.

        Yields:
            One ``TranscriptionFrame``, or an ``ErrorFrame`` when the request
            fails. A failure is reported and dropped rather than retried: by the
            time a retry returned, the turn it belonged to would be over.
        """
        if self._http is None:
            yield ErrorFrame(error=f"{self}: transcription before start")
            return

        await self.start_ttfb_metrics()
        payload = self._request_body(audio)
        try:
            response = await self._http.post(
                self._url, headers=self._headers, json=payload
            )
        except httpx.HTTPError as exc:
            # Includes the timeout. Degrade the turn, do not end the call: the
            # turn controller's ceiling still fires and the agent stays responsive.
            logger.warning(f"{self}: transcription failed: {type(exc).__name__}: {exc}")
            yield ErrorFrame(error=f"{self}: {exc}")
            return
        finally:
            await self.stop_ttfb_metrics()

        if response.status_code != 200:
            # The error body is JSON even though a success body is too; what is
            # worth logging is the vendor's message, not the shape.
            logger.error(
                f"{self}: transcription failed ({response.status_code}): {response.text}"
            )
            yield ErrorFrame(error=f"{self}: openrouter {response.status_code}")
            return

        result = response.json()
        self._note_language(result.get("language"))
        text = (result.get("text") or "").strip()
        if not text:
            # Silence, or a segment the vendor made nothing of. Not an error,
            # and emitting an empty turn would be worse than saying nothing.
            yield None
            return

        self._utterance.finals.append(text)
        # Usage is already reported: `SegmentedSTTService._handle_user_stopped_speaking`
        # accounts for the buffer and flushes it before `run_stt` ever runs.
        yield TranscriptionFrame(
            text,
            self._user_id,
            time_now_iso8601(),
            self._language,
            finalized=True,
        )

    def _request_body(self, audio: bytes) -> dict[str, Any]:
        """The JSON one transcription request carries."""
        body: dict[str, Any] = dict(self._body)
        body.update(
            {
                "model": self._settings.model,
                "input_audio": {
                    # Bare base64. A `data:` URI here is rejected as invalid.
                    "data": base64.b64encode(audio).decode("ascii"),
                    "format": AUDIO_FORMAT,
                },
            }
        )
        language = self._language_code
        if language:
            body["language"] = language
        return body

    def _note_language(self, reported: Any) -> None:
        if not isinstance(reported, str) or not reported.strip():
            return
        code = reported.strip().lower().replace("_", "-")
        if code != self._detected_language:
            self._detected_language = code
            logger.debug(f"{self}: vendor reported language {code!r}")

    # -- helpers -----------------------------------------------------------

    @property
    def _language(self) -> Language | None:
        """The call's language as a Pipecat enum, for tagging frames.

        Pipecat's enum is case-sensitive about the regional half (``pt-BR``,
        not ``pt-br``) while a language row is lowercase throughout, so the
        canonical casing is tried before the literal value. An unmatched code
        leaves the frame untagged rather than mislabelled — the transcript is
        still correct, and the row is the thing to fix.
        """
        language = self._settings.language
        if isinstance(language, Language):
            return language
        raw = str(language or "").strip().replace("_", "-")
        base, _, region = raw.partition("-")
        for candidate in (
            f"{base.lower()}-{region.upper()}" if region else "",
            raw,
            raw.lower(),
        ):
            try:
                return Language(candidate)
            except ValueError:
                continue
        return None

    @property
    def _language_code(self) -> str | None:
        """The call's language as the ISO-639-1 subtag the endpoint documents.

        ``pt-br`` goes out as ``pt``: the field is specified as ISO-639-1, and a
        regional tag is the kind of value a vendor accepts and silently ignores.
        """
        language = self._settings.language
        raw = language.value if isinstance(language, Language) else str(language or "")
        base = raw.strip().lower().replace("_", "-").split("-")[0]
        return base or None


SttAdapters[SttAdapterEnum.openrouter] = OpenRouterSTTAdapter
