"""Text-to-text (LLM) adapters and their registry.

Kept separate from the chat service's ``AIAdapters`` on purpose: a call agent
streams tokens under a latency budget and speaks the result, while a chat
assistant returns a message. The registry shape is the same so the two read
alike, but the contract is a Pipecat ``LLMService`` in the pipeline.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Self

from pipecat.services.llm_service import LLMService

from src.application.engine.capabilities import TttCapabilities
from src.application.engine.config import TttConfig
from src.common.enums.engine import TttAdapterEnum


class BaseTttAdapter(LLMService):
    """Contract every language model client in this package satisfies."""

    capabilities: TttCapabilities = TttCapabilities()

    @classmethod
    @abstractmethod
    def from_config(cls, config: TttConfig) -> Self:
        """Build a client for one call.

        Args:
            config: Resolved LLM settings — endpoint, model, sampling.

        Returns:
            A ready service.
        """


#: Registry. Populated by each adapter module at import time.
TttAdapters: dict[TttAdapterEnum, type[BaseTttAdapter]] = {}


def build_ttt(config: TttConfig) -> BaseTttAdapter:
    """Resolve and build the language model named by `config`.

    Args:
        config: Resolved LLM settings.

    Returns:
        A service, with the organization's capability overrides applied.

    Raises:
        KeyError: if no adapter is registered under that name.
    """
    adapter = TttAdapters.get(config.adapter)
    if adapter is None:
        raise KeyError(
            f"no TTT adapter registered as {config.adapter!r}. "
            f"Registered: {sorted(TttAdapters)}"
        )
    service = adapter.from_config(config)
    service.capabilities = adapter.capabilities.merged(config.model.capabilities)
    return service
