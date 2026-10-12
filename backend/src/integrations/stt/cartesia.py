"""Cartesia Live STT: a hosted recogniser behind the same registry contract.

The first paid recogniser in this package, and it differs from the self-hosted
ones in exactly the ways the capability data exists to describe:

======================  ============================  =========================
                        Qwen3-ASR / Voxtral (vLLM)    Cartesia Live
======================  ============================  =========================
transport               vLLM's ``/v1/realtime``       ``/stt/websocket``, with
                                                      the session pinned in the
                                                      query string
auth                    ``Authorization: Bearer``     ``X-API-Key`` plus a
                                                      pinned ``Cartesia-Version``
end of utterance        inferred (newline, silence)   ``is_final`` on the
                                                      transcript event
minimum buffer          5s, or a commit returns       none; it is a streaming
                        nothing                       API, not a commit API
audio sent              only while the VAD gate is    the whole call
                        open                          (see below)
======================  ============================  =========================

The wire protocol itself is Pipecat's :class:`CartesiaSTTService`; this module
is the adapter around it — ``from_config``, the capability declaration, the
16 kHz conversion through the call's :class:`AudioPath`, and the local
transcript buffer :meth:`flush` answers the turn controller from.

Two deliberate differences from the self-hosted clients:

* **No VAD gate.** Qwen3-ASR streams only while Silero says the caller is
  speaking, because a self-hosted GPU is paid for by the second of decoding.
  Cartesia is billed per minute of audio and keeps one session per connection
  that its own endpointing runs on, so the audio flows continuously and the
  ``finalize`` command (sent by the Pipecat service on VAD stop) is what closes
  an utterance early.
* **No commit padding.** There is no commit: transcripts stream, and a final
  arrives when the server says ``is_final``.

One more vendor fact worth knowing where it bites: Cartesia drops a connection
after three minutes of inactivity, which a call with a quiet caller reaches
easily. Pipecat's client keeps it alive with silence (its own 30s interval),
which is another reason the audio here is not gated on the VAD.

Every capability below is taken from Cartesia's documentation and the Pipecat
client, **not** measured against a live account the way the vLLM backends were.
Treat ``min_commit_seconds``, ``tail_silence_seconds`` and ``reports_language``
as the first things to re-check once there is real traffic, and correct them
from the model row rather than here if the account disagrees.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Final
from urllib.parse import urlsplit

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.services.cartesia.stt import CartesiaSTTService

from src.application.engine.audio import ASR_SAMPLE_RATE, AudioPath
from src.application.engine.capabilities import SttCapabilities
from src.application.engine.config import SttConfig
from src.common.enums.engine import SttAdapterEnum
from src.integrations.stt.base import BaseSttAdapter, SttAdapters, UtteranceBuffer

#: Where Cartesia is served when a provider row leaves the URL empty.
DEFAULT_HOST: Final[str] = "api.cartesia.ai"

#: Default served model. ``ink-whisper`` is the one Pipecat defaults to; the
#: ``ink-2`` family is what keyterm biasing needs.
DEFAULT_STT_MODEL: Final[str] = "ink-whisper"

#: What this client assumes that the protocol does not state.
PROTOCOL_ASSUMPTIONS: Final[tuple[str, ...]] = (
    "the connection is TLS (wss); the vendor client dials no plain-ws host",
    (
        "a transcript with is_final=true ends that segment, and a turn may be "
        "several of them"
    ),
    (
        "a transcript event without a language field means the account's model "
        "does not report one, not that detection failed"
    ),
)


def stt_base_url(url: str | None) -> str:
    """The host (and proxy path prefix) Cartesia's client appends its route to.

    Pipecat's client builds ``wss://{base_url}/stt/websocket?…`` itself, so it
    wants a host, not a URL. A provider row stores the same shape it stores for
    every other backend — ``https://api.cartesia.ai`` — and this drops the
    parts the vendor client adds back, keeping a reverse-proxy prefix intact:
    ``https://gw.example.com/cartesia`` becomes ``gw.example.com/cartesia``.

    Args:
        url: The provider row's URL, in any of the shapes an operator writes it:
            a full URL, a bare host, or empty.

    Returns:
        ``host[:port][/prefix]``, never with a scheme.
    """
    if not url or not url.strip():
        return DEFAULT_HOST
    raw = url.strip()
    # A bare host ("api.cartesia.ai") parses as a path, not a netloc; the
    # "//" prefix is what makes urlsplit read it as the authority it is.
    parsed = urlsplit(raw if "//" in raw else f"//{raw}")
    if not parsed.netloc:
        return DEFAULT_HOST
    return f"{parsed.netloc}{parsed.path.rstrip('/')}"


class CartesiaSTTAdapter(BaseSttAdapter, CartesiaSTTService):
    """Cartesia Live transcription, as one of the engine's recognisers.

    Both bases are load-bearing for the same reason they are on
    :class:`~src.integrations.stt.qwen3_asr.Qwen3ASRService`: ``BaseSttAdapter``
    is the registry contract, and the vendor class brings the wire protocol.
    """

    protocol_assumptions: tuple[str, ...] = PROTOCOL_ASSUMPTIONS

    #: Documented behaviour, not measured behaviour — see the module docstring.
    #:
    #: ``min_commit_seconds`` and ``tail_silence_seconds`` are zero because this
    #: backend has no commit: audio streams and finals arrive on their own. The
    #: two flags exist for backends where a commit is the only way to get text,
    #: and setting them non-zero here would pad audio nothing is waiting for.
    #: ``reports_language`` is false because Cartesia's documentation does not
    #: claim language detection — the vendor client reads a ``language`` field
    #: if one arrives, and :attr:`detected_language` surfaces it, but an
    #: organization should turn this on from its row only once it has seen the
    #: field on its own traffic. Declaring a signal that never comes is what
    #: leaves the language switcher waiting forever.
    capabilities: SttCapabilities = SttCapabilities(
        streams_during_speech=True,
        emits_completion_event=True,
        min_commit_seconds=0.0,
        tail_silence_seconds=0.0,
        reports_language=False,
        server_turn_detection=False,
        sample_rate=ASR_SAMPLE_RATE,
        accepts_language_hint=True,
    )

    @classmethod
    def from_config(
        cls, config: SttConfig, *, call_id: str, audio_path: AudioPath
    ) -> CartesiaSTTAdapter:
        """Build a client from an organization's STT row.

        ``provider.options`` carries what has no column: ``keyterms`` (a list of
        phrases to bias towards, honoured by ink-2 models only) and anything
        under ``client`` that the vendor service accepts.
        """
        options = config.model.provider.options
        api_key = config.model.provider.api_key
        if not api_key:
            # Cartesia has no anonymous tier, so this is always a misconfigured
            # row. Said here, at build time, rather than as a socket that opens
            # and closes without a transcript.
            logger.warning(
                f"cartesia stt: no api_key on provider {config.model.provider.url!r}; "
                "the handshake will be rejected"
            )
        return cls(
            api_key=api_key or "",
            base_url=stt_base_url(config.model.provider.url),
            settings=CartesiaSTTService.Settings(
                model=config.model.code or DEFAULT_STT_MODEL,
                language=config.language or "en",
                keyterm=options.get("keyterms"),
            ),
            # The rate the query string announces, and the rate this adapter
            # converts every frame to below. Not the transport's rate.
            sample_rate=ASR_SAMPLE_RATE,
            encoding="pcm_s16le",
            audio_path=audio_path,
            **options.get("client", {}),
        )

    def __init__(self, *, audio_path: AudioPath | None = None, **kwargs: Any) -> None:
        """Initialise the client.

        Args:
            audio_path: The call's converters, shared with the transport. One is
                created if not supplied.
            **kwargs: Passed to :class:`CartesiaSTTService`.
        """
        super().__init__(**kwargs)
        # Pipecat 1.8 keeps only the host of ``base_url`` and dials
        # ``{host}/stt/websocket``, silently dropping the reverse-proxy prefix
        # stt_base_url() preserves. The dialed URI joins this attribute and the
        # route verbatim, so handing the prefix back restores the proxied route.
        base_url = kwargs.get("base_url") or ""
        prefix = urlsplit(base_url if "//" in base_url else f"//{base_url}").path
        if prefix.rstrip("/"):
            self._base_url = f"{self._base_url}{prefix.rstrip('/')}"
        self._audio_path = audio_path or AudioPath(asr_sample_rate=ASR_SAMPLE_RATE)
        # The transport's rate, learned at setup. Kept separately
        # because `self.sample_rate` is pinned to what Cartesia is told to
        # expect, so it can no longer double as "the rate audio arrives at".
        self._transport_sample_rate = ASR_SAMPLE_RATE
        self._utterance = UtteranceBuffer()
        self._detected_language: str | None = None

    # -- public surface ----------------------------------------------------

    def flush(self) -> str:
        """Return the transcript accumulated for the current turn and clear it.

        Local bookkeeping only. The server's own finals are what fill this
        buffer, but the turn controller cannot wait for one at commit time.
        """
        text = self._utterance.text()
        self._utterance.clear()
        return text

    @property
    def detected_language(self) -> str | None:
        """Language the last transcript event reported, as a lowercase code.

        ``None`` until the server reports one — which some model/account
        combinations never do, which is why this is read rather than assumed.
        """
        return self._detected_language

    # -- audio in ----------------------------------------------------------

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Note the transport's rate before anything connects.

        Read from the setup rather than the ``StartFrame``, whose copy is
        deprecated since Pipecat 1.8.0.
        """
        self._transport_sample_rate = setup.audio_in_sample_rate or ASR_SAMPLE_RATE
        await super().setup(setup)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None]:
        """Convert one frame to the rate the session was opened with, then send it.

        The conversion runs through the call's :class:`AudioPath` for the reason
        it always does: the resampler carries filter state, so one instance must
        serve one stream.

        Args:
            audio: 16-bit mono PCM at the transport's rate.

        Yields:
            Whatever the vendor service yields — nothing, in practice;
            transcripts arrive on its receive task.
        """
        pcm = await self._audio_path.to_asr(audio, self._transport_sample_rate)
        if not pcm:
            # The stream resampler primes its filter on the first frame of a
            # rate change and returns nothing; an empty binary frame on the
            # wire would be this client inventing a message the protocol has
            # no meaning for.
            yield None
            return
        async for frame in super().run_stt(pcm):
            yield frame

    # -- transcripts out ---------------------------------------------------

    async def _on_transcript(self, data: dict[str, Any]) -> None:
        """Record the segment locally, then let the vendor service push it.

        Two things happen here that the vendor service does not do: finals are
        accumulated so :meth:`flush` can answer the turn controller, and a
        transcript with no language of its own is tagged with the call's, so a
        frame never reaches the transcript hooks unlabelled.
        """
        text = (data.get("text") or "").strip()
        if text:
            reported = data.get("language")
            if reported:
                self._detected_language = str(reported).strip().lower()
            elif self._settings.language:
                data = {**data, "language": self._settings.language}
            if data.get("is_final"):
                self._utterance.finals.append(text)
                self._utterance.partial = ""
            else:
                self._utterance.partial = text
        await super()._on_transcript(data)


SttAdapters[SttAdapterEnum.cartesia] = CartesiaSTTAdapter
