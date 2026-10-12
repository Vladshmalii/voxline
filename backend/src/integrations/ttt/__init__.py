"""Text-to-text (LLM) adapters.

Importing this package registers every built-in client in
:data:`~src.integrations.ttt.base.TttAdapters`.
"""

from src.integrations.ttt.base import BaseTttAdapter, TttAdapters, build_ttt
from src.integrations.ttt.openai_compatible import OpenAICompatibleLLMService

__all__ = ["BaseTttAdapter", "OpenAICompatibleLLMService", "TttAdapters", "build_ttt"]
