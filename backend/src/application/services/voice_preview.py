"""Agent voice preview synthesis service.

Generates a short audio sample for testing agent voices across all supported
TTS backends (Cartesia, Deepgram, OpenRouter, Qwen3-TTS / OpenAI-compatible).
"""

from __future__ import annotations

import io
import wave
from typing import Final

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.engine.config import TtsConfig
from src.application.services.model_assignment import default_model
from src.common.enums.engine import ProviderKindEnum, TtsAdapterEnum
from src.integrations.tts.cartesia import (
    cartesia_language,
)
from src.models.provider import Model
from src.repositories.agent import _model_config
from src.repositories.provider import ModelCRUD
from src.schemas.admin import SDirectVoicePreviewRequest
from src.utils.url import http_url

REQUEST_TIMEOUT_SECONDS: Final[float] = 15.0

DEFAULT_SAMPLE_PHRASES: Final[dict[str, str]] = {
    "ru": "Здравствуйте! Я ваш голосовой ассистент.",
    "en": "Hello! I am your voice assistant.",
    "es": "¡Hola! Soy su asistente de voz.",
    "de": "Hallo! Ich bin Ihr Sprachassistent.",
    "fr": "Bonjour! Je suis votre assistant vocal.",
    "it": "Ciao! Sono il tuo assistente vocale.",
    "pt": "Olá! Eu sou seu assistente de voz.",
}


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """Wraps raw 16-bit PCM bytes into a standard WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return buf.getvalue()


class VoicePreviewError(ValueError):
    """No sample could be synthesized; the message says why."""


class PreviewModelNotFound(LookupError):
    """The requested ``model_id`` is no active TTS model in this organization."""


class VoicePreviewService:
    def __init__(self, session: AsyncSession | None = None) -> None:
        #: Only :meth:`preview_direct` reads model rows; synthesis is stateless.
        self.session = session

    @staticmethod
    def default_text_for_language(language: str | None) -> str:
        code = (language or "ru").split("-")[0].lower()
        return DEFAULT_SAMPLE_PHRASES.get(code, DEFAULT_SAMPLE_PHRASES["ru"])

    async def preview(
        self,
        config: TtsConfig,
        text: str | None = None,
        language: str | None = None,
    ) -> tuple[bytes, str]:
        """:meth:`synthesize`, with a vendor refusal or an unreachable vendor
        raised as :class:`VoicePreviewError`."""
        try:
            return await self.synthesize(config, text=text, language=language)
        except (ValueError, httpx.HTTPError) as exc:
            raise VoicePreviewError(str(exc)) from exc

    async def preview_direct(
        self, data: SDirectVoicePreviewRequest, *, default_only: bool
    ) -> tuple[bytes, str]:
        """Sample audio for a voice and model/adapter, without needing an agent.

        Args:
            data: The voice, and optionally which model or adapter speaks it.
            default_only: Use the organization's default TTS model, whatever
                ``data`` names — the only choice a non-administrator has.

        Returns:
            ``(audio_bytes, media_type)``.

        Raises:
            PreviewModelNotFound: If ``data.model_id`` is no active TTS model.
            VoicePreviewError: If no TTS model fits, or the synthesiser
                refused or was unreachable.
        """
        tts_model = await self._direct_model(data, default_only=default_only)
        try:
            adapter_enum = TtsAdapterEnum(tts_model.adapter)
        except ValueError:
            adapter_enum = TtsAdapterEnum.openrouter

        tts_config = TtsConfig(
            adapter=adapter_enum,
            model=_model_config(tts_model),
            voice=data.voice,
            language=data.language or "ru",
            speed=data.speed,
        )
        return await self.preview(tts_config, text=data.text, language=data.language)

    async def _direct_model(
        self, data: SDirectVoicePreviewRequest, *, default_only: bool
    ) -> Model:
        models = ModelCRUD(self.session)
        tts_model: Model | None = None
        if default_only:
            tts_model = await default_model(self.session, ProviderKindEnum.tts)
        elif data.model_id:
            tts_model = await models.get_one_or_none(
                Model.id == data.model_id,
                Model.kind == ProviderKindEnum.tts,
                Model.is_active.is_(True),
            )
            if not tts_model:
                raise PreviewModelNotFound(f"Model id {data.model_id} not found")
        elif data.adapter:
            # Any TTS model with that adapter, even an inactive one.
            tts_model = await models.preferred(
                Model.kind == ProviderKindEnum.tts, Model.adapter == data.adapter
            )
            if not tts_model:
                raise VoicePreviewError(
                    f"TTS model for adapter '{data.adapter}' is not configured in this organization. Please add a {data.adapter} TTS model on the Models page."
                )

        # If neither model_id nor adapter specified, fallback to any TTS model in the system
        if not tts_model:
            tts_model = await models.preferred(Model.kind == ProviderKindEnum.tts)

        if not tts_model:
            raise VoicePreviewError(
                "No TTS model configured in the system. Please configure a TTS model on the Models page."
            )
        return tts_model

    async def synthesize(
        self,
        config: TtsConfig,
        text: str | None = None,
        language: str | None = None,
    ) -> tuple[bytes, str]:
        """Synthesizes sample audio for the given TTS configuration.

        Args:
            config: Resolved TtsConfig.
            text: Optional custom text to speak.
            language: Optional language code.

        Returns:
            Tuple of (audio_bytes, media_type)
        """
        lang = (language or config.language or "ru").strip().lower()
        phrase = (
            text.strip()
            if text and text.strip()
            else self.default_text_for_language(lang)
        )

        adapter = config.adapter

        if adapter == TtsAdapterEnum.cartesia:
            return await self._synthesize_cartesia(config, phrase, lang)
        elif adapter == TtsAdapterEnum.deepgram:
            return await self._synthesize_deepgram(config, phrase)
        elif adapter in (TtsAdapterEnum.openrouter, TtsAdapterEnum.qwen3_tts):
            return await self._synthesize_openai_compatible(config, phrase)
        else:
            return await self._synthesize_openai_compatible(config, phrase)

    async def _synthesize_cartesia(
        self, config: TtsConfig, text: str, language: str
    ) -> tuple[bytes, str]:
        base_url = (
            http_url(config.model.provider.url)
            if config.model.provider.url
            else "https://api.cartesia.ai"
        )
        url = f"{base_url.rstrip('/')}/tts/bytes"

        lang_code = cartesia_language(language)
        model_code = config.model.code
        # Cartesia REST API models: sonic-multilingual (for non-en or multilingual), sonic-english, sonic
        if not model_code or model_code in ("cartesia", "sonic-3.5", "default"):
            model_code = "sonic-multilingual" if lang_code != "en" else "sonic-english"
        elif lang_code != "en" and model_code == "sonic-english":
            model_code = "sonic-multilingual"

        headers = {
            "X-API-Key": config.model.provider.api_key or "",
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }
        body: dict = {
            "model_id": model_code,
            "transcript": text,
            "voice": {"mode": "id", "id": config.voice},
            "output_format": {
                "container": "wav",
                "sample_rate": config.sample_rate or 24000,
                "encoding": "pcm_s16le",
            },
            "language": lang_code,
        }
        if config.speed is not None:
            body["generation_config"] = {"speed": config.speed}

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=body)
            if not resp.is_success:
                err_msg = resp.text
                try:
                    err_json = resp.json()
                    err_msg = (
                        err_json.get("error") or err_json.get("message") or resp.text
                    )
                except (ValueError, AttributeError):
                    logger.debug(f"could not parse Cartesia error body: {resp.text!r}")
                logger.error(f"Cartesia preview failed ({resp.status_code}): {err_msg}")
                raise ValueError(f"Cartesia error ({resp.status_code}): {err_msg}")
            return resp.content, "audio/wav"

    async def _synthesize_deepgram(
        self, config: TtsConfig, text: str
    ) -> tuple[bytes, str]:
        voice = config.voice or config.model.code or "aura-2-helena-en"
        base_url = (
            http_url(config.model.provider.url)
            if config.model.provider.url
            else "https://api.deepgram.com"
        )
        url = f"{base_url.rstrip('/')}/v1/speak?model={voice}&container=wav"

        headers = {
            "Authorization": f"Token {config.model.provider.api_key or ''}",
            "Content-Type": "application/json",
        }
        body = {"text": text}

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=body)
            if not resp.is_success:
                err_msg = resp.text
                try:
                    err_json = resp.json()
                    err_msg = (
                        err_json.get("err_msg") or err_json.get("error") or resp.text
                    )
                except (ValueError, AttributeError):
                    logger.debug(f"could not parse Deepgram error body: {resp.text!r}")
                logger.error(f"Deepgram preview failed ({resp.status_code}): {err_msg}")
                raise ValueError(f"Deepgram error ({resp.status_code}): {err_msg}")
            return resp.content, "audio/wav"

    async def _synthesize_openai_compatible(
        self, config: TtsConfig, text: str
    ) -> tuple[bytes, str]:
        base_url = (
            http_url(config.model.provider.url)
            if config.model.provider.url
            else "https://openrouter.ai/api/v1"
        )
        base = base_url.rstrip("/")
        url = f"{base}/audio/speech" if not base.endswith("/audio/speech") else base

        headers = {
            "Authorization": f"Bearer {config.model.provider.api_key or ''}",
            "Content-Type": "application/json",
        }
        model_name = config.model.code or "openai/tts-1"
        if not "/" in model_name and "openrouter" in base:
            model_name = f"openai/{model_name}"

        body: dict = {
            "model": model_name,
            "input": text,
            "voice": config.voice,
            "response_format": "wav",
        }
        if config.speed is not None:
            body["speed"] = config.speed

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=body)
            if not resp.is_success:
                err_msg = resp.text
                try:
                    err_json = resp.json()
                    if isinstance(err_json, dict):
                        err_msg = (
                            err_json.get("error", {}).get("message")
                            if isinstance(err_json.get("error"), dict)
                            else err_json.get("error")
                            or err_json.get("message")
                            or resp.text
                        )
                except (ValueError, AttributeError):
                    logger.debug(f"could not parse TTS error body: {resp.text!r}")
                logger.error(
                    f"OpenAI/OpenRouter preview failed ({resp.status_code}): {err_msg}"
                )
                raise ValueError(f"TTS error ({resp.status_code}): {err_msg}")

            content_type = resp.headers.get("content-type", "audio/wav")
            # If server returned raw PCM without header
            if "pcm" in content_type:
                return pcm_to_wav(
                    resp.content, sample_rate=config.sample_rate or 24000
                ), "audio/wav"
            return resp.content, content_type
