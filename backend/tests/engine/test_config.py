"""Resolving an organization's configuration into one call's settings.

The merge is where a misconfiguration turns into a customer hearing the wrong
voice in the wrong language, so it is pinned here rather than trusted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.application.engine.capabilities import SttCapabilities
from src.application.engine.config import (
    CallContext,
    ChunkingConfig,
    CustomerProfile,
    LanguageConfig,
    PromptSet,
    SpokenPrompts,
    SttConfig,
    TurnParams,
    resolve_profile,
)
from src.common.enums.engine import CallDirectionEnum, ChunkingModeEnum, SttAdapterEnum
from tests.engine.conftest import make_model

RU_PROMPTS = PromptSet(
    system_prompt="Ты голосовой агент.", greeting_kickoff="Начни разговор."
)
RU_SPOKEN = SpokenPrompts(
    silence="Вы ещё на связи?", reprompt="Продолжайте.", goodbye="До свидания."
)


def call(**overrides) -> CallContext:
    defaults = {"call_id": "call-1", "org_uuid": "org-1"}
    defaults.update(overrides)
    return CallContext(**defaults)


def test_a_call_with_no_language_uses_the_agent_default(agent):
    profile = resolve_profile(agent, call())

    assert profile.language == "en"
    assert profile.prompts is agent.prompts


def test_a_configured_language_replaces_the_sections_it_sets(agent):
    agent.languages["ru"] = LanguageConfig(
        language="ru", voice="serena", prompts=RU_PROMPTS, spoken=RU_SPOKEN
    )

    profile = resolve_profile(agent, call(language="ru"))

    assert profile.language == "ru"
    assert profile.tts.voice == "serena"
    assert profile.prompts.system_prompt.startswith("Ты")
    # Untouched sections still come from the agent.
    assert profile.turn == agent.turn
    assert profile.ttt is agent.ttt


def test_a_rendered_call_script_wins_over_every_prompt_layer(agent):
    """The campaign's rendered script is per-call fact: it replaces the
    script in whatever PromptSet the layers resolved to, and only the script —
    the system prompt and greeting stay whose they were."""
    agent.languages["ru"] = LanguageConfig(language="ru", prompts=RU_PROMPTS)

    profile = resolve_profile(
        agent, call(language="ru", call_script="Предложи бонус WB50.")
    )

    assert profile.prompts.call_script == "Предложи бонус WB50."
    assert profile.prompts.system_prompt == RU_PROMPTS.system_prompt
    # None means "no campaign": the resolved layers keep their own script.
    untouched = resolve_profile(agent, call(language="ru"))
    assert untouched.prompts.call_script == RU_PROMPTS.call_script


def test_a_regional_tag_falls_back_to_the_base_language(agent):
    agent.languages["ru"] = LanguageConfig(language="ru", voice="serena")

    assert resolve_profile(agent, call(language="ru-RU")).tts.voice == "serena"
    assert resolve_profile(agent, call(language="RU_ru")).tts.voice == "serena"


def test_an_unconfigured_language_keeps_the_defaults(agent):
    """A caller speaking something nobody configured still gets a working call."""
    profile = resolve_profile(agent, call(language="sv"))

    assert profile.language == "sv"
    assert profile.tts.voice == agent.tts.voice
    assert profile.prompts is agent.prompts


def test_the_call_overrides_the_language(agent):
    """Per-call overrides are what an A/B run and a support reproduction use."""
    agent.languages["ru"] = LanguageConfig(language="ru", voice="serena")

    profile = resolve_profile(
        agent,
        call(language="ru", overrides=LanguageConfig(language="ru", voice="uncle_fu")),
    )

    assert profile.tts.voice == "uncle_fu"


def test_a_language_may_route_to_a_different_recogniser(agent):
    """The reason the registry exists: one agent, two backends, by language."""
    agent.languages["ru"] = LanguageConfig(
        language="ru",
        stt=SttConfig(
            adapter=SttAdapterEnum.voxtral,
            model=make_model("voxtral", "wss://voxtral/v1/realtime"),
        ),
    )

    assert (
        resolve_profile(agent, call(language="ru")).stt.adapter
        == SttAdapterEnum.voxtral
    )
    assert resolve_profile(agent, call()).stt.adapter == SttAdapterEnum.qwen3_asr


def test_the_stt_language_defaults_to_the_call_language(agent):
    """Backends that ignore the hint still tag their frames with it."""
    profile = resolve_profile(agent, call(language="ru"))

    assert profile.stt.language == "ru"


def test_an_inbound_call_never_speaks_first(agent):
    """The greeting kickoff exists for outbound; inbound waits for the caller."""
    outbound = resolve_profile(agent, call(direction=CallDirectionEnum.outbound))
    inbound = resolve_profile(agent, call(direction=CallDirectionEnum.inbound))

    assert outbound.greet_first is True
    assert inbound.greet_first is False


def test_the_clients_idle_timeout_beats_the_agents(agent):
    """VOAD-68: a callee's own timeout wins; without one the agent's stands."""
    default = resolve_profile(agent, call())
    custom = resolve_profile(agent, call(idle_timeout_seconds=45))

    assert default.idle_timeout_seconds == agent.idle_timeout_seconds
    assert custom.idle_timeout_seconds == 45


def test_chunking_can_be_switched_per_language(agent):
    """Trading latency for one voice per turn is a per-language decision."""
    agent.languages["ru"] = LanguageConfig(
        language="ru", chunking=ChunkingConfig(mode=ChunkingModeEnum.whole_turn)
    )

    assert (
        resolve_profile(agent, call(language="ru")).chunking.mode
        == ChunkingModeEnum.whole_turn
    )
    assert resolve_profile(agent, call()).chunking.mode == ChunkingModeEnum.clause


def test_the_summary_names_everything_a_call_runs_with(agent):
    """One log line has to answer "why did this call behave like that"."""
    summary = resolve_profile(agent, call()).summary()

    for expected in (
        "language=en",
        "stt=qwen3_asr",
        "tts=qwen3_tts",
        "ttt=openai_compatible",
    ):
        assert expected in summary


def test_a_turn_window_that_cannot_hold_a_cascade_is_refused():
    with pytest.raises(ValidationError, match="exceeds max_delay_ms"):
        TurnParams(min_delay_ms=3000, max_delay_ms=200)

    with pytest.raises(ValidationError, match="repoll_ms must be positive"):
        TurnParams(repoll_ms=0)


def test_delays_are_available_in_seconds():
    """Operators type milliseconds; asyncio takes seconds."""
    params = TurnParams(min_delay_ms=200, max_delay_ms=3000, repoll_ms=400)

    assert params.min_delay == 0.2
    assert params.max_delay == 3.0
    assert params.repoll_interval == 0.4


def test_the_customer_reaches_the_prompt_but_not_the_cacheable_prefix(agent):
    """Layer 2 varies per call; layer 1 must not, or the prefix cache is lost."""
    from src.application.engine.pipeline import build_context

    context, assembler, _ = build_context(
        resolve_profile(agent, call()),
        call(customer=CustomerProfile(customer_id="C-1", name="Anna")),
    )
    messages = context.get_messages()

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Anna" in messages[1]["content"]
    assert "Anna" not in messages[0]["content"]
    assert assembler.stable_prefix_signature()


async def _stub_sms(_body: str) -> str:
    return "SMS sent."


def test_the_sms_tool_is_off_by_default(agent):
    """No toggle, no tool — a customer's agent that never mentions SMS must
    not suddenly be able to send one."""
    from pipecat.processors.aggregators.llm_context import NOT_GIVEN

    from src.application.engine.pipeline import build_context

    context, _, sms_intent = build_context(
        resolve_profile(agent, call()),
        call(
            customer=CustomerProfile(
                customer_id="C-1", name="Anna", phone="+15550001111"
            )
        ),
        agent=agent,
        send_sms=_stub_sms,
    )

    assert context.tools is NOT_GIVEN
    assert sms_intent is None


def test_the_sms_tool_appears_when_enabled_with_a_phone_and_a_sender(agent):
    """The things the tool needs: the toggle, an approved message, a number
    to text, and something to actually send it with (later, at call end)."""
    from src.application.engine.pipeline import build_context

    agent.sms_tool_enabled = True
    agent.sms_tool_message = "Your deposit bonus is ready — reply STOP to opt out."

    context, _, sms_intent = build_context(
        resolve_profile(agent, call()),
        call(
            customer=CustomerProfile(
                customer_id="C-1", name="Anna", phone="+15550001111"
            )
        ),
        agent=agent,
        send_sms=_stub_sms,
    )

    tools = context.tools.standard_tools
    assert len(tools) == 1
    assert tools[0].name == "send_sms"
    assert "Your deposit bonus is ready" in tools[0].description
    assert sms_intent is not None
    assert sms_intent.requested is False


def test_the_sms_tool_stays_off_without_a_phone_number(agent):
    """Nothing to text is the same as nothing to text with — no tool offered."""
    from pipecat.processors.aggregators.llm_context import NOT_GIVEN

    from src.application.engine.pipeline import build_context

    agent.sms_tool_enabled = True
    agent.sms_tool_message = "Your deposit bonus is ready."

    context, _, sms_intent = build_context(
        resolve_profile(agent, call()),
        call(customer=CustomerProfile(customer_id="C-1", name="Anna")),
        agent=agent,
        send_sms=_stub_sms,
    )

    assert context.tools is NOT_GIVEN
    assert sms_intent is None


def test_the_sms_tool_stays_off_without_a_sender(agent):
    """A True toggle with nothing wired to send through it must not crash a
    diagnostics run or a test that has no infrastructure behind it."""
    from pipecat.processors.aggregators.llm_context import NOT_GIVEN

    from src.application.engine.pipeline import build_context

    agent.sms_tool_enabled = True
    agent.sms_tool_message = "Your deposit bonus is ready."

    context, _, sms_intent = build_context(
        resolve_profile(agent, call()),
        call(
            customer=CustomerProfile(
                customer_id="C-1", name="Anna", phone="+15550001111"
            )
        ),
        agent=agent,
        send_sms=None,
    )

    assert context.tools is NOT_GIVEN
    assert sms_intent is None


def test_the_sms_tool_stays_off_with_a_blank_message(agent):
    """The toggle alone isn't enough (VOAD-60) — there must be actual text to
    send, or the model would be offered a tool with nothing to say."""
    from pipecat.processors.aggregators.llm_context import NOT_GIVEN

    from src.application.engine.pipeline import build_context

    agent.sms_tool_enabled = True

    context, _, sms_intent = build_context(
        resolve_profile(agent, call()),
        call(
            customer=CustomerProfile(
                customer_id="C-1", name="Anna", phone="+15550001111"
            )
        ),
        agent=agent,
        send_sms=_stub_sms,
    )

    assert context.tools is NOT_GIVEN
    assert sms_intent is None


def test_the_sms_tool_stays_off_while_pending_moderation(agent):
    """Staff-authored text a moderator hasn't approved yet must never reach
    the model — the tool isn't even advertised (VOAD-62)."""
    from pipecat.processors.aggregators.llm_context import NOT_GIVEN

    from src.application.engine.pipeline import build_context
    from src.common.enums.engine import SmsMessageStatusEnum

    agent.sms_tool_enabled = True
    agent.sms_tool_message = "Your deposit bonus is ready."
    agent.sms_tool_message_status = SmsMessageStatusEnum.pending

    context, _, sms_intent = build_context(
        resolve_profile(agent, call()),
        call(
            customer=CustomerProfile(
                customer_id="C-1", name="Anna", phone="+15550001111"
            )
        ),
        agent=agent,
        send_sms=_stub_sms,
    )

    assert context.tools is NOT_GIVEN
    assert sms_intent is None


def test_capability_overrides_apply_on_top_of_the_adapter_defaults():
    """An organization corrects a deployment that disagrees with its docs."""
    merged = SttCapabilities(tail_silence_seconds=1.5).merged(
        {"tail_silence_seconds": 2.5}
    )

    assert merged.tail_silence_seconds == 2.5
    assert merged.min_commit_seconds == 5.0


def test_an_unknown_capability_is_ignored_rather_than_fatal():
    """A typo in one organization's row must not take its calls down."""
    merged = SttCapabilities().merged({"tale_silence_seconds": 2.5})

    assert merged == SttCapabilities()


# ---------------------------------------------------------------------------
# WebSocket URL derivation: one provider row serves https and wss clients
# ---------------------------------------------------------------------------


def stt(url: str, **options) -> SttConfig:
    model = make_model("test-asr", url)
    model.provider.options.update(options)
    return SttConfig(adapter=SttAdapterEnum.qwen3_asr, model=model)


def test_an_https_provider_row_resolves_to_the_wss_realtime_endpoint():
    """The row stores one HTTP base; the adapter owns the scheme and route."""
    assert (
        stt("https://llm.example.net").websocket_url()
        == "wss://llm.example.net/v1/realtime"
    )
    assert (
        stt("http://127.0.0.1:8100").websocket_url()
        == "ws://127.0.0.1:8100/v1/realtime"
    )


def test_a_reverse_proxy_prefix_survives_the_derivation():
    assert (
        stt("https://gw.example.net/vllm/").websocket_url()
        == "wss://gw.example.net/vllm/v1/realtime"
    )


def test_a_full_ws_url_is_used_verbatim():
    """An operator who pasted the realtime URL knows their layout best."""
    url = "wss://llm.example.net/custom/realtime"
    assert stt(url, ws_path="/ignored").websocket_url() == url


def test_ws_path_in_options_overrides_the_adapter_default_route():
    """The documented home for 'a non-standard path' actually steers it."""
    assert (
        stt("https://llm.example.net", ws_path="/asr/stream").websocket_url()
        == "wss://llm.example.net/asr/stream"
    )


def test_a_scheme_that_is_neither_http_nor_ws_is_refused():
    with pytest.raises(ValueError, match="ftp"):
        stt("ftp://llm.example.net").websocket_url()
