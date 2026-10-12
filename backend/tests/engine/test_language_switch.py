"""Mid-call language switching: hysteresis, the atomic swap, and its refusals.

The three conversations these tests encode:

* a caller who moves to a configured language gets the whole profile — voice,
  prompts, spoken lines, turn timing — swapped at one seam;
* a caller who borrows one sentence does not flip the call;
* a language row that only a pipeline rebuild could honour is refused with the
  blockers named, and the call carries on in the language it started in.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    STTUpdateSettingsFrame,
    TranscriptionFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.config import (
    CallContext,
    ChunkingConfig,
    LanguageConfig,
    LanguageSwitchPolicy,
    PromptSet,
    SpokenPrompts,
    SttConfig,
    TurnParams,
    resolve_profile,
)
from src.application.engine.context.assembly import (
    AgentScript,
    CustomerProfile,
    PromptAssembler,
)
from src.application.engine.language_switch import LanguageSwitcher, hot_switch_blockers
from src.application.engine.readiness import check_language_switch
from src.common.enums.engine import SttAdapterEnum
from src.integrations.stt.qwen3_asr import language_code
from tests.engine.conftest import make_agent, make_model, make_profile

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class FakeStt:
    """The one thing the switcher reads from the recogniser."""

    def __init__(self) -> None:
        self.detected_language: str | None = None


class FakeProfileTarget:
    """Records apply_profile calls; stands in for the strategy and silence."""

    def __init__(self) -> None:
        self.applied = []

    def apply_profile(self, profile) -> None:
        self.applied.append(profile)


class FakeContext:
    """Stands in for LLMContext; only `.messages` is touched."""

    def __init__(self, messages: list[dict]) -> None:
        self.messages = messages


def de_row(**overrides) -> LanguageConfig:
    """A German language row that is hot-switchable unless overridden."""
    base = {
        "language": "de",
        "voice": "voice-de",
        "prompts": PromptSet(
            system_prompt="Du bist ein Sprachagent.", call_script="Begrüßen, helfen."
        ),
        "spoken": SpokenPrompts(
            silence="Sind Sie noch dran?",
            reprompt="Bitte weiter.",
            goodbye="Auf Wiederhören.",
        ),
        "turn": TurnParams(smart_turn=False),
    }
    base.update(overrides)
    return LanguageConfig(**base)


def make_switcher(agent=None, call=None, customer: CustomerProfile | None = None):
    """A switcher wired to fakes, plus everything a test wants to inspect."""
    agent = agent or make_agent(
        languages={"de": de_row()},
        language_switch=LanguageSwitchPolicy(enabled=True),
    )
    call = call or CallContext(call_id="call-1", org_uuid="org-1")
    profile = resolve_profile(agent, call)
    assembler = PromptAssembler(
        AgentScript(
            system_prompt=profile.prompts.system_prompt,
            script=profile.prompts.call_script,
        ),
        customer,
    )
    context = FakeContext(assembler.initial_messages())

    stt = FakeStt()
    strategy = FakeProfileTarget()
    silence = FakeProfileTarget()
    switcher = LanguageSwitcher(
        agent=agent,
        call=call,
        profile=profile,
        stt=stt,
        strategy=strategy,
        silence=silence,
        context=context,
        assembler=assembler,
    )

    pushed: list[tuple[object, FrameDirection]] = []

    async def record_push(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append((frame, direction))

    switcher.push_frame = record_push

    events: list[dict] = []

    async def record_event(payload: dict) -> None:
        events.append(payload)

    switcher.notify = record_event
    return switcher, stt, strategy, silence, context, pushed, events


async def hear(switcher, stt, text: str, detected: str | None) -> None:
    """One final utterance reaches the switcher."""
    stt.detected_language = detected
    await switcher._observe(TranscriptionFrame(text, "caller", "t0"))


# ---------------------------------------------------------------------------
# Hysteresis
# ---------------------------------------------------------------------------


async def test_a_single_foreign_utterance_does_not_switch():
    switcher, stt, strategy, silence, _, pushed, _ = make_switcher()

    await hear(switcher, stt, "Können wir auf Deutsch sprechen?", "de")

    assert switcher.profile.language == "en"
    assert not strategy.applied and not silence.applied and not pushed


async def test_a_borrowed_sentence_resets_the_streak():
    switcher, stt, strategy, *_ = make_switcher()

    await hear(switcher, stt, "Ich rufe wegen der Rechnung an.", "de")
    await hear(switcher, stt, "Sorry, the invoice from March.", "en")
    await hear(switcher, stt, "Die Rechnung von März bitte.", "de")

    assert switcher.profile.language == "en"
    assert not strategy.applied


async def test_short_utterances_count_neither_for_nor_against():
    switcher, stt, *_ = make_switcher()

    await hear(switcher, stt, "Ich rufe wegen der Rechnung an.", "de")
    # Two words: below min_utterance_words. Must not reset the pending streak.
    await hear(switcher, stt, "Ja gut.", "de")
    await hear(switcher, stt, "Die Rechnung von März bitte.", "de")

    assert switcher.profile.language == "de"


async def test_a_backend_that_reports_nothing_leaves_it_inert():
    """Voxtral never reports a language; the switcher must never fire."""
    switcher, stt, strategy, silence, _, pushed, events = make_switcher()

    await hear(switcher, stt, "Können wir auf Deutsch sprechen?", None)
    await hear(switcher, stt, "Die Rechnung von März bitte.", None)

    assert switcher.profile.language == "en"
    assert not strategy.applied and not silence.applied and not pushed and not events


async def test_an_unconfigured_language_never_switches():
    switcher, stt, strategy, *_ = make_switcher()

    await hear(switcher, stt, "Est-ce que je peux parler français?", "fr")
    await hear(switcher, stt, "Je voudrais vérifier ma commande.", "fr")

    assert switcher.profile.language == "en"
    assert not strategy.applied


# ---------------------------------------------------------------------------
# The switch itself
# ---------------------------------------------------------------------------


async def test_a_confirmed_switch_swaps_the_whole_profile():
    switcher, stt, strategy, silence, context, pushed, events = make_switcher()

    await hear(switcher, stt, "Können wir auf Deutsch sprechen?", "de")
    await hear(switcher, stt, "Ich rufe wegen meiner Bestellung an.", "de")

    assert switcher.profile.language == "de"
    assert switcher.switches == [("en", "de")]

    # Turn strategy and silence handler re-profiled with the German row.
    assert strategy.applied[-1].language == "de"
    assert strategy.applied[-1].turn.smart_turn is False
    assert silence.applied[-1].spoken.silence == "Sind Sie noch dran?"

    # Layer 1 rewritten in place, so this very turn is answered in German.
    assert "Du bist ein Sprachagent." in context.messages[0]["content"]

    # The recogniser is retagged upstream; the synthesiser retargeted downstream.
    stt_updates = [(f, d) for f, d in pushed if isinstance(f, STTUpdateSettingsFrame)]
    tts_updates = [(f, d) for f, d in pushed if isinstance(f, TTSUpdateSettingsFrame)]
    assert len(stt_updates) == 1 and stt_updates[0][1] == FrameDirection.UPSTREAM
    assert stt_updates[0][0].delta.language == "de"
    assert len(tts_updates) == 1 and tts_updates[0][1] == FrameDirection.DOWNSTREAM
    assert tts_updates[0][0].delta.voice == "voice-de"
    assert tts_updates[0][0].delta.language == "de"

    assert events[-1]["event"] == "language_switched"
    assert (events[-1]["from"], events[-1]["to"]) == ("en", "de")


async def test_the_call_can_switch_back_to_the_default_language():
    """The default usually has no row of its own; it must still be a target."""
    switcher, stt, strategy, _, context, *_ = make_switcher()

    await hear(switcher, stt, "Können wir auf Deutsch sprechen?", "de")
    await hear(switcher, stt, "Ich rufe wegen meiner Bestellung an.", "de")
    await hear(switcher, stt, "Actually, English is fine after all.", "en")
    await hear(switcher, stt, "Let us continue in English please.", "en")

    assert switcher.profile.language == "en"
    assert switcher.switches == [("en", "de"), ("de", "en")]
    assert strategy.applied[-1].turn.smart_turn is True
    assert "You are a voice agent." in context.messages[0]["content"]


async def test_per_call_overrides_survive_a_switch():
    """A support override rides along, exactly as it would at call start."""
    call = CallContext(
        call_id="call-1",
        org_uuid="org-1",
        overrides=LanguageConfig(language="override", voice="voice-pinned"),
    )
    switcher, stt, *_, pushed, _ = make_switcher(call=call)

    await hear(switcher, stt, "Können wir auf Deutsch sprechen?", "de")
    await hear(switcher, stt, "Ich rufe wegen meiner Bestellung an.", "de")

    assert switcher.profile.language == "de"
    assert switcher.profile.tts.voice == "voice-pinned"
    tts_update = next(f for f, _ in pushed if isinstance(f, TTSUpdateSettingsFrame))
    assert tts_update.delta.voice == "voice-pinned"


async def test_the_rewrite_preserves_history_and_the_customer_layer():
    customer = CustomerProfile(customer_id="cust-1", name="Anna", language="en")
    switcher, stt, _, _, context, *_ = make_switcher(customer=customer)
    context.messages += [
        {"role": "user", "content": "Hallo, können wir Deutsch sprechen?"},
        {"role": "assistant", "content": "Of course."},
    ]
    length_before = len(context.messages)

    await hear(switcher, stt, "Können wir auf Deutsch sprechen?", "de")
    await hear(switcher, stt, "Ich rufe wegen meiner Bestellung an.", "de")

    assert len(context.messages) == length_before
    assert "Du bist ein Sprachagent." in context.messages[0]["content"]
    assert "Preferred language: de" in context.messages[1]["content"]
    assert context.messages[-2]["content"] == "Hallo, können wir Deutsch sprechen?"
    assert context.messages[-1]["content"] == "Of course."


# ---------------------------------------------------------------------------
# Refusals: model boundaries
# ---------------------------------------------------------------------------


def boundary_agent() -> object:
    """An agent whose German row routes to a different recogniser."""
    return make_agent(
        languages={
            "de": de_row(
                stt=SttConfig(
                    adapter=SttAdapterEnum.voxtral,
                    model=make_model("other-asr", "ws://127.0.0.1:59109/v1/realtime"),
                )
            )
        },
        language_switch=LanguageSwitchPolicy(enabled=True),
    )


async def test_a_switch_across_a_model_boundary_is_refused():
    switcher, stt, strategy, silence, _, pushed, events = make_switcher(
        agent=boundary_agent()
    )

    await hear(switcher, stt, "Können wir auf Deutsch sprechen?", "de")
    await hear(switcher, stt, "Ich rufe wegen meiner Bestellung an.", "de")

    assert switcher.profile.language == "en"
    assert not strategy.applied and not silence.applied and not pushed
    assert events[-1]["event"] == "language_switch_refused"
    assert any("stt" in blocker for blocker in events[-1]["blockers"])


async def test_a_refusal_is_reported_once_not_per_utterance():
    switcher, stt, *_, events = make_switcher(agent=boundary_agent())

    for _ in range(4):
        await hear(switcher, stt, "Ich rufe wegen meiner Bestellung an.", "de")

    assert len(events) == 1


# ---------------------------------------------------------------------------
# hot_switch_blockers: what a rebuild-free switch may and may not change
# ---------------------------------------------------------------------------


def test_identical_profiles_have_no_blockers():
    profile = make_profile()
    assert hot_switch_blockers(profile, profile) == []


def test_a_voice_change_is_not_a_blocker():
    active = make_profile()
    new = active.model_copy(
        update={"tts": active.tts.model_copy(update={"voice": "other"})}
    )
    assert hot_switch_blockers(active, new) == []


def test_an_stt_language_tag_is_not_a_blocker():
    active = make_profile()
    new = active.model_copy(
        update={"stt": active.stt.model_copy(update={"language": "de"})}
    )
    assert hot_switch_blockers(active, new) == []


def test_service_and_shape_changes_are_blockers():
    active = make_profile()
    cases = {
        "stt": {
            "stt": active.stt.model_copy(update={"model": make_model("other-asr")})
        },
        "ttt": {"ttt": active.ttt.model_copy(update={"temperature": 0.9})},
        "tts": {"tts": active.tts.model_copy(update={"sample_rate": 48000})},
        "vad": {"vad": active.vad.model_copy(update={"confidence": 0.9})},
        "chunking": {"chunking": ChunkingConfig(min_words=20)},
    }
    for name, update in cases.items():
        blockers = hot_switch_blockers(active, active.model_copy(update=update))
        assert blockers and name in blockers[0], f"{name}: {blockers}"


# ---------------------------------------------------------------------------
# Readiness: refusals should be visible before a caller finds them
# ---------------------------------------------------------------------------


def test_readiness_reports_switchable_languages():
    agent = make_agent(
        languages={"de": de_row()},
        language_switch=LanguageSwitchPolicy(enabled=True),
    )
    checks = check_language_switch(agent)
    assert [(c.key, c.ok) for c in checks] == [("language_switch:de", True)]


def test_readiness_names_the_blockers():
    checks = check_language_switch(boundary_agent())
    assert len(checks) == 1
    assert not checks[0].ok
    assert "stt" in checks[0].detail


def test_readiness_is_silent_when_the_policy_is_off():
    agent = make_agent(languages={"de": de_row()})
    assert agent.language_switch.enabled is False
    assert check_language_switch(agent) == []


# ---------------------------------------------------------------------------
# The recogniser's normalisation: names on the wire, codes in the engine
# ---------------------------------------------------------------------------


def test_preamble_names_normalise_to_codes():
    assert language_code("Russian") == "ru"
    assert language_code("English") == "en"
    assert language_code("German") == "de"
    # Already a code: passes through.
    assert language_code("pt") == "pt"
    # Unknown names stay visible rather than vanishing.
    assert language_code("Beijing_Dialect") == "beijing-dialect"
