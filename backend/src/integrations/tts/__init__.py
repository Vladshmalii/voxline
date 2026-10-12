"""Text-to-speech adapters.

Importing this package registers every built-in synthesiser in
:data:`~src.integrations.tts.base.TtsAdapters`.
"""

from src.integrations.tts.base import BaseTtsAdapter, TtsAdapters, build_tts
from src.integrations.tts.cartesia import CartesiaTTSAdapter
from src.integrations.tts.deepgram import DeepgramTTSAdapter
from src.integrations.tts.openrouter import OpenRouterTTSAdapter
from src.integrations.tts.qwen3_tts import Qwen3TTSService

__all__ = [
    "BaseTtsAdapter",
    "CartesiaTTSAdapter",
    "DeepgramTTSAdapter",
    "OpenRouterTTSAdapter",
    "Qwen3TTSService",
    "TtsAdapters",
    "build_tts",
]
