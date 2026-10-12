"""Speech-to-text adapters and the registry the engine resolves them through.

An adapter is a Pipecat ``STTService`` that knows how to build itself from an
organization's :class:`SttConfig` and declares what it does through
:class:`SttCapabilities`. The engine never imports a module from this package —
it looks a name up in :data:`SttAdapters`, the same way the chat service
resolves ``AIAdapters[assistant.provider_type]``.

Adding a recogniser: subclass, declare capabilities, implement ``from_config``,
register at the bottom of the module, import it in ``__init__``.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Self

from pipecat.services.stt_service import STTService

from src.application.engine.audio import AudioPath
from src.application.engine.capabilities import SttCapabilities
from src.application.engine.config import SttConfig
from src.common.enums.engine import SttAdapterEnum


@dataclass
class UtteranceBuffer:
    """Transcript accumulated for the utterance currently in flight.

    Local snapshots are available through :meth:`BaseSttAdapter.flush`.
    The live pipeline consumes transcription frames instead: an interim in
    this buffer must not be mistaken for text committed to the LLM context.
    """

    finals: list[str] = field(default_factory=list)
    partial: str = ""

    def text(self) -> str:
        """Everything transcribed so far, finals plus the live partial."""
        parts = [*self.finals, self.partial]
        return " ".join(p.strip() for p in parts if p.strip())

    def clear(self) -> None:
        """Drop everything."""
        self.finals.clear()
        self.partial = ""


class BaseSttAdapter(STTService):
    """Contract every recogniser in this package satisfies."""

    #: What this client assumes about a protocol it cannot negotiate. Logged
    #: once per call from the adapter actually selected, so swapping the
    #: recogniser swaps the caveats with it.
    protocol_assumptions: tuple[str, ...] = ()

    #: Defaults, overridable per organization from the model row.
    capabilities: SttCapabilities = SttCapabilities()

    @classmethod
    @abstractmethod
    def from_config(
        cls, config: SttConfig, *, call_id: str, audio_path: AudioPath
    ) -> Self:
        """Build a client for one call.

        Per call, never shared: two organizations point at different endpoints
        with different keys, and a pooled client would cross that line.

        Args:
            config: The resolved STT settings for this call.
            call_id: Correlation id, passed to backends that accept a session id.
            audio_path: The call's converters, shared with the transport.

        Returns:
            A ready client. It must not open a connection until it sees a
            ``StartFrame``.
        """

    @property
    def detected_language(self) -> str | None:
        """Language the server reported, when it reports one at all.

        Returned as a lowercase language code (``"ru"``, ``"pt-br"``) — each
        adapter normalises whatever its server actually says, because the
        consumers (the language switcher, the logs) speak codes and must not
        know one backend announces names while another says nothing.

        Observed, not commanded. A persistent disagreement with the call's
        language is a routing signal, not something to silently override.
        """
        return None

    def flush(self) -> str:
        """Return the transcript accumulated for the current utterance and clear it.

        Local bookkeeping only; the live turn controller consumes frames and
        waits for a transcript that the user aggregator can actually commit.
        """
        return ""


#: Registry. Populated by each adapter module at import time.
SttAdapters: dict[SttAdapterEnum, type[BaseSttAdapter]] = {}


def build_stt(
    config: SttConfig, *, call_id: str, audio_path: AudioPath
) -> BaseSttAdapter:
    """Resolve and build the recogniser named by `config`.

    Args:
        config: Resolved STT settings.
        call_id: Correlation id for the call.
        audio_path: The call's converters.

    Returns:
        A client, with the organization's capability overrides applied.

    Raises:
        KeyError: if no adapter is registered under that name.
    """
    adapter = SttAdapters.get(config.adapter)
    if adapter is None:
        raise KeyError(
            f"no STT adapter registered as {config.adapter!r}. "
            f"Registered: {sorted(SttAdapters)}"
        )
    service = adapter.from_config(config, call_id=call_id, audio_path=audio_path)
    service.capabilities = adapter.capabilities.merged(config.model.capabilities)
    return service
