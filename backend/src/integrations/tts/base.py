"""Text-to-speech adapters and their registry.

Same shape as the STT package: a Pipecat ``TTSService`` that builds itself from
an organization's :class:`TtsConfig` and declares its behaviour through
:class:`TtsCapabilities`. The chunking policy the engine applies is chosen from
those capabilities — a synthesiser that streams incrementally wants different
chunk sizes from one that returns a whole clip at once.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Self

from pipecat.services.tts_service import TTSService

from src.application.engine.capabilities import TtsCapabilities
from src.application.engine.config import ChunkingConfig, TtsConfig
from src.common.enums.engine import TtsAdapterEnum


class BaseTtsAdapter(TTSService):
    """Contract every synthesiser in this package satisfies."""

    capabilities: TtsCapabilities = TtsCapabilities()

    @classmethod
    @abstractmethod
    def from_config(cls, config: TtsConfig, chunking: ChunkingConfig) -> Self:
        """Build a synthesiser for one call.

        Args:
            config: Resolved TTS settings, including the voice.
            chunking: How replies are cut on the way in. The adapter installs
                the matching text aggregator, because Pipecat fixes one in its
                constructor and exposes no setter.

        Returns:
            A ready service.
        """


#: Registry. Populated by each adapter module at import time.
TtsAdapters: dict[TtsAdapterEnum, type[BaseTtsAdapter]] = {}


def build_tts(config: TtsConfig, chunking: ChunkingConfig) -> BaseTtsAdapter:
    """Resolve and build the synthesiser named by `config`.

    Args:
        config: Resolved TTS settings.
        chunking: Chunking policy for this call.

    Returns:
        A service, with the organization's capability overrides applied.

    Raises:
        KeyError: if no adapter is registered under that name.
    """
    adapter = TtsAdapters.get(config.adapter)
    if adapter is None:
        raise KeyError(
            f"no TTS adapter registered as {config.adapter!r}. "
            f"Registered: {sorted(TtsAdapters)}"
        )
    service = adapter.from_config(config, chunking)
    service.capabilities = adapter.capabilities.merged(config.model.capabilities)
    return service
