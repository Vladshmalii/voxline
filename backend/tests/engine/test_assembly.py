"""Prompt assembly: the ordering invariants that keep vLLM's prefix cache warm.

Each test here maps to a way the cache gets destroyed in practice. They are cheap
and they run without network, so there is no excuse for a regression.
"""

from __future__ import annotations

from src.application.engine.context.assembly import (
    PROFILE_ROLE,
    AgentScript,
    CustomerProfile,
    PromptAssembler,
    append_retrieved_context,
    signature_of,
)

SCRIPT = AgentScript(system_prompt="You are a voice agent.", script="Greet, then help.")


def profile(customer_id: str = "C-1", **kwargs) -> CustomerProfile:
    return CustomerProfile(customer_id=customer_id, **kwargs)


def history(turns: int) -> list[dict]:
    messages: list[dict] = []
    for i in range(turns):
        messages.append({"role": "user", "content": f"question {i}"})
        messages.append({"role": "assistant", "content": f"answer {i}"})
    return messages


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_layers_are_ordered_most_stable_first():
    assembler = PromptAssembler(SCRIPT, profile())
    messages = assembler.build(history(2))

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == PROFILE_ROLE
    assert "Customer id: C-1" in messages[1]["content"]
    assert [m["role"] for m in messages[2:]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_system_message_carries_no_per_call_content():
    """The single most expensive mistake: a name or a timestamp in layer 1."""
    assembler = PromptAssembler(SCRIPT, profile(name="Dana Whitfield"))
    system = assembler.build(history(1))[0]["content"]

    assert "Dana" not in system
    assert "C-1" not in system


def test_system_message_is_identical_across_calls():
    """Layer 1 is shared between every call on the fleet, or it is worth nothing."""
    a = PromptAssembler(SCRIPT, profile("C-1", name="Dana")).build(history(3))
    b = PromptAssembler(SCRIPT, profile("C-2", name="Ravi")).build([])

    assert a[0] == b[0]


def test_profile_is_its_own_message_not_folded_into_system():
    """Folding it in would cost the cross-call hit, which is the larger win."""
    with_profile = PromptAssembler(SCRIPT, profile()).build([])
    without_profile = PromptAssembler(SCRIPT, None).build([])

    assert with_profile[0] == without_profile[0]
    assert len(with_profile) == 2
    assert len(without_profile) == 1


def test_stable_prefix_signature_survives_a_growing_conversation():
    """If this ever changes mid-call, something is writing per-turn data into layer 1 or 2."""
    assembler = PromptAssembler(SCRIPT, profile(name="Dana"))
    signature = assembler.stable_prefix_signature()

    for turns in range(1, 6):
        messages = assembler.build(history(turns))
        assert signature_of(messages[:2]) == signature


def test_profile_renders_deterministically():
    """Dict iteration order must not decide whether the cache hits."""
    one = CustomerProfile("C-1", attributes={"tier": "gold", "region": "eu"})
    two = CustomerProfile("C-1", attributes={"region": "eu", "tier": "gold"})

    assert one.render() == two.render()


# ---------------------------------------------------------------------------
# Layer 4: per-turn retrieved context
# ---------------------------------------------------------------------------


def test_retrieved_context_lands_on_the_final_user_message():
    messages = PromptAssembler(SCRIPT, profile()).build(history(2))
    result = append_retrieved_context(messages, "Order A-1 shipped Tuesday.")

    assert "Order A-1 shipped Tuesday." in result[-2]["content"]
    assert result[-2]["role"] == "user"


def test_retrieved_context_leaves_every_earlier_token_untouched():
    """An insert in the middle moves every token after it and forces a full prefill."""
    messages = PromptAssembler(SCRIPT, profile()).build(history(3))
    result = append_retrieved_context(messages, "Some retrieved fact.")

    last_user = max(i for i, m in enumerate(result) if m["role"] == "user")
    assert result[:last_user] == messages[:last_user]
    assert len(result) == len(messages)


def test_retrieved_context_does_not_mutate_the_input():
    messages = PromptAssembler(SCRIPT, profile()).build(history(1))
    before = signature_of(messages)

    append_retrieved_context(messages, "A fact.")

    assert signature_of(messages) == before


def test_empty_retrieved_context_is_a_noop():
    messages = PromptAssembler(SCRIPT, profile()).build(history(1))
    assert append_retrieved_context(messages, "   ") == messages


def test_retrieved_context_never_lands_on_the_customer_profile():
    """The profile is a `user` message, so an unguarded append would write
    per-turn text onto the stable prefix and invalidate the cache every turn."""
    assembler = PromptAssembler(SCRIPT, profile())
    messages = assembler.build([])  # no history yet — profile is the last user msg
    result = assembler.append_turn_context(messages, "A fact.")

    assert result == messages
    assert all("A fact." not in str(m["content"]) for m in result)


def test_protected_prefix_is_honoured_once_history_exists():
    assembler = PromptAssembler(SCRIPT, profile())
    messages = assembler.build(history(2))
    result = assembler.append_turn_context(messages, "A fact.")

    prefix_len = len(assembler.stable_prefix())
    assert result[:prefix_len] == messages[:prefix_len]
    assert "A fact." in result[-2]["content"]


def test_signature_is_unchanged_by_a_turn_context_append():
    assembler = PromptAssembler(SCRIPT, profile())
    messages = assembler.build(history(1))
    before = assembler.stable_prefix_signature()

    result = assembler.append_turn_context(messages, "A fact.")

    assert signature_of(result[: len(assembler.stable_prefix())]) == before


def test_retrieved_context_appends_to_multimodal_content():
    messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    result = append_retrieved_context(messages, "A fact.")

    assert len(result[0]["content"]) == 2
    assert "A fact." in result[0]["content"][1]["text"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def test_no_tools_are_exported():
    """Tools are deliberately absent: some served models reject a request that
    carries them at all, rather than ignoring them."""
    from src.application.engine.context import assembly

    assert not hasattr(assembly, "build_tools")
    assert not hasattr(assembly, "lookup_customer_order")


def test_agent_script_renders_both_halves():
    rendered = SCRIPT.render()
    assert rendered.startswith("You are a voice agent.")
    assert "Greet, then help." in rendered


def test_agent_script_without_a_script_is_just_the_system_prompt():
    assert AgentScript(system_prompt="Only this.").render() == "Only this."
