"""Any OpenAI-compatible chat endpoint: vLLM, LiteLLM, OpenRouter, OpenAI.

The whole client is Pipecat's ``OpenAILLMService``; what this module adds is the
translation from an organization's row into its settings, and one default worth
stating out loud.

**Thinking is off unless asked for.** Measured against a deployed Qwen3.6
endpoint: with reasoning on, a greeting burned 300 tokens of
``reasoning_content`` in 2.7 s and emitted no speech at all; with it off, 0.5 s
and a clean reply. On a phone call there is nobody to read the reasoning and no
budget to wait for it, so :attr:`TttConfig.enable_thinking` defaults to False
and travels in ``extra_body`` where an OpenAI-shaped client will not drop it.

The engine advertises ``end_call`` and, when configured, ``send_sms`` through
the LLM context. The endpoint must support automatic function calling. Set
``supports_tools=False`` on a model without that support to disable the built-in
end-call tool, and leave SMS disabled for that model as well.
"""

from __future__ import annotations

from pipecat.services.openai.base_llm import OpenAILLMSettings
from pipecat.services.openai.llm import OpenAILLMService

from src.application.engine.capabilities import TttCapabilities
from src.application.engine.config import TttConfig
from src.common.enums.engine import TttAdapterEnum
from src.integrations.ttt.base import BaseTttAdapter, TttAdapters


class OpenAICompatibleLLMService(OpenAILLMService, BaseTttAdapter):
    """Chat completions over an OpenAI-compatible route."""

    capabilities: TttCapabilities = TttCapabilities(
        supports_tools=True,
        prefix_cache=True,
        reasoning_toggle=True,
        streams=True,
    )

    @classmethod
    def from_config(cls, config: TttConfig) -> OpenAICompatibleLLMService:
        """Build a client from an organization's LLM row.

        Args:
            config: Resolved LLM settings — endpoint, model, sampling.

        Returns:
            A ready service.
        """
        extra_body = dict(config.extra_body)
        if config.enable_thinking is not None:
            # vLLM's chat template switch. Servers that do not know it ignore it.
            template_kwargs = dict(extra_body.get("chat_template_kwargs", {}))
            template_kwargs.setdefault("enable_thinking", config.enable_thinking)
            extra_body["chat_template_kwargs"] = template_kwargs

        return cls(
            base_url=config.model.provider.url,
            # vLLM ignores the value, but the OpenAI client refuses to construct
            # without one, so a non-empty placeholder is the sane default.
            api_key=config.model.provider.api_key or "not-needed",
            settings=OpenAILLMSettings(
                model=config.model.code,
                temperature=config.temperature,
                top_p=config.top_p,
                max_tokens=config.max_tokens,
                extra={"extra_body": extra_body} if extra_body else {},
            ),
        )


TttAdapters[TttAdapterEnum.openai_compatible] = OpenAICompatibleLLMService
