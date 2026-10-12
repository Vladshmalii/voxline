"""Speech-to-text adapters.

Importing this package registers every built-in recogniser in
:data:`~src.integrations.stt.base.SttAdapters`. The engine resolves by name and
never imports a module from here directly.
"""

from src.integrations.stt.base import (
    BaseSttAdapter,
    SttAdapters,
    UtteranceBuffer,
    build_stt,
)
from src.integrations.stt.cartesia import CartesiaSTTAdapter
from src.integrations.stt.deepgram import DeepgramSTTAdapter
from src.integrations.stt.openrouter import OpenRouterSTTAdapter
from src.integrations.stt.qwen3_asr import Qwen3ASRService
from src.integrations.stt.voxtral import VoxtralRealtimeService

__all__ = [
    "BaseSttAdapter",
    "CartesiaSTTAdapter",
    "DeepgramSTTAdapter",
    "OpenRouterSTTAdapter",
    "Qwen3ASRService",
    "SttAdapters",
    "UtteranceBuffer",
    "VoxtralRealtimeService",
    "build_stt",
]
