"""Prompt assembly ordered for vLLM's prefix cache.

vLLM caches the KV blocks of a prompt prefix and reuses them for any later
request that starts with the same tokens. The saving is proportional to how long
that shared prefix is, and it is destroyed by the *first* byte that differs. So
the order of the prompt is not a stylistic choice — it decides how much of every
turn's prefill is recomputed.

The order, most stable first::

    1. system prompt + script   identical on every call, for every customer
    2. customer profile         fixed at dial time, identical for every turn of a call
    3. conversation history     grows by two messages per turn
    4. per-turn retrieved context, appended to the FINAL user message

Layer 1 is shared across *calls*, so on a busy dialer it is nearly always already
resident. Layer 2 is shared across the *turns* of one call. Layers 3 and 4 are the
only parts that must be prefilled fresh.

**The mistake this module exists to prevent** is putting anything that changes
into the system prompt — the customer's name, the time of day, a retrieved
snippet. Doing so invalidates the cache for the entire prompt that follows it, on
every single turn, and costs more time-to-first-token than any other single
decision in the pipeline. That is also why retrieved context is appended to the
last user message instead of inserted as its own message earlier: an insert in the
middle moves every token after it.

:func:`stable_prefix_signature` exists so this is testable and observable — it
hashes the layers that must not change, and the tests assert it stays put as a
conversation grows.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Final

from loguru import logger

Message = dict[str, Any]

#: Role used for the customer-profile layer.
#:
#: It has to be its own message rather than an addendum to the system prompt, or
#: layer 1 stops being byte-identical across calls and the cross-call cache hit
#: is lost — which is the larger of the two wins.
#:
#: ``user`` rather than ``system``: Qwen3.6 served through vLLM rejects a second
#: system message outright with *"System message must be at the beginning."*
#: Many chat templates only special-case ``messages[0]``. The caching properties
#: are identical either way — the profile is still its own message in the same
#: position — so only the framing changes.
PROFILE_ROLE: Final[str] = "user"

_RETRIEVED_HEADER: Final[str] = "\n\n[Context retrieved for this turn]\n"


@dataclass(frozen=True, slots=True)
class AgentScript:
    """Layer 1: the part of the prompt that is the same on every call.

    Keep this free of anything per-call. If a value differs between two calls it
    belongs in :class:`CustomerProfile` or later.
    """

    system_prompt: str
    script: str = ""

    def render(self) -> str:
        """Render layers 1a and 1b into one message body."""
        if not self.script:
            return self.system_prompt.strip()
        return f"{self.system_prompt.strip()}\n\n{self.script.strip()}"


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    """Layer 2: what is known about this customer, fetched at dial time.

    Frozen on purpose. A profile that can be mutated mid-call is a profile that
    silently invalidates the cache for every turn after the mutation.
    """

    customer_id: str
    name: str = ""
    language: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    offers: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        """Render the profile as a stable, deterministically ordered block."""
        lines = [f"Customer id: {self.customer_id}"]
        if self.name:
            lines.append(f"Name: {self.name}")
        if self.language:
            lines.append(f"Preferred language: {self.language}")
        # Sorted so two profiles with the same content always render the same
        # bytes; dict order must not decide whether the cache hits.
        for key in sorted(self.attributes):
            lines.append(f"{key}: {self.attributes[key]}")
        if self.offers:
            lines.append(
                "Offers you may propose to this customer, and no others. If they "
                "decline one, you may offer a different one from this list:"
            )
            for offer in self.offers:
                lines.append(f"- {offer}")
        return "Customer profile for this call:\n" + "\n".join(lines)


class PromptAssembler:
    """Builds the message list in prefix-cache order."""

    def __init__(
        self, script: AgentScript, profile: CustomerProfile | None = None
    ) -> None:
        """Initialise the assembler.

        Args:
            script: Layer 1, the call-invariant instructions.
            profile: Layer 2, this call's customer. May be absent for inbound
                calls where the caller is not yet identified.
        """
        self._script = script
        self._profile = profile

    @property
    def script(self) -> AgentScript:
        """Layer 1."""
        return self._script

    @property
    def profile(self) -> CustomerProfile | None:
        """Layer 2."""
        return self._profile

    def stable_prefix(self) -> list[Message]:
        """Layers 1 and 2: everything that must not change during the call."""
        messages: list[Message] = [{"role": "system", "content": self._script.render()}]
        if self._profile is not None:
            messages.append({"role": PROFILE_ROLE, "content": self._profile.render()})
        return messages

    def initial_messages(self) -> list[Message]:
        """The message list a call starts with, ready for ``LLMContext``."""
        return self.stable_prefix()

    def build(self, history: list[Message] | None = None) -> list[Message]:
        """Assemble the full message list.

        Args:
            history: Layer 3, the conversation so far. Must not contain the
                system or profile messages.

        Returns:
            A new list; the inputs are not mutated.
        """
        return [*self.stable_prefix(), *(history or [])]

    def append_turn_context(
        self, messages: list[Message], retrieved: str
    ) -> list[Message]:
        """Attach this turn's retrieved context, protecting layers 1 and 2.

        Prefer this over calling :func:`append_retrieved_context` directly: it
        knows how long the stable prefix is, so per-turn text can never land on
        the customer-profile message.
        """
        return append_retrieved_context(
            messages, retrieved, protect_first=len(self.stable_prefix())
        )

    def stable_prefix_signature(self) -> str:
        """Hash of layers 1 and 2, for cache-stability assertions and logging.

        Two calls with the same signature share a cacheable prefix; if this value
        changes between turns of one call, something is writing per-turn content
        into a layer that must stay fixed.
        """
        return signature_of(self.stable_prefix())


def signature_of(messages: list[Message]) -> str:
    """Stable hash of a message list."""
    blob = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def append_retrieved_context(
    messages: list[Message], retrieved: str, *, protect_first: int = 0
) -> list[Message]:
    """Append per-turn retrieved context to the final user message.

    Layer 4. Appending to the last message keeps every preceding token identical,
    so the cache still covers everything up to the current turn. Inserting the
    same text as its own message — or, worse, into the system prompt — would move
    every token after the insertion point and force a full prefill.

    Args:
        messages: The assembled message list. Not mutated.
        retrieved: Context for this turn. Empty or blank is a no-op.
        protect_first: Number of leading messages that must never be written to.
            The customer profile is carried as a ``user`` message (see
            :data:`PROFILE_ROLE`), so without this a first turn with no history
            would append per-turn text straight onto the stable prefix and
            invalidate the cache on every single turn — the exact failure this
            module exists to prevent. :meth:`PromptAssembler.append_turn_context`
            passes the right value for you.

    Returns:
        A new list with the context appended to the last eligible user message.
        If there is none, the input is returned unchanged and a warning logged —
        retrieval with nothing to attach to means the caller has the order wrong.
    """
    if not retrieved.strip():
        return list(messages)

    result = [dict(m) for m in messages]
    for index in range(len(result) - 1, max(0, protect_first) - 1, -1):
        message = result[index]
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = f"{content}{_RETRIEVED_HEADER}{retrieved.strip()}"
        elif isinstance(content, list):
            # Multimodal content: append a text part rather than stringify.
            message["content"] = [
                *content,
                {"type": "text", "text": f"{_RETRIEVED_HEADER}{retrieved.strip()}"},
            ]
        else:
            logger.warning(
                "retrieved context: last user message has unusable content type"
            )
            return list(messages)
        return result

    logger.warning("retrieved context discarded: no user message to append to")
    return list(messages)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
#
# Deliberately none. No tool schema is advertised and no `tools` array is sent,
# so the agent runs against any chat model — including the many Ollama tags that
# reject a request carrying tools outright ("<model> does not support tools",
# HTTP 400) rather than ignoring them.
#
# To reintroduce them: build a `ToolsSchema` of `FunctionSchema` objects, pass it
# as `LLMContext(messages=..., tools=...)` in bot.py, register each handler with
# `llm.register_function(name, handler)`, and tell the model about them in
# CALL_SCRIPT. Advertise the full set once at call start and never change it
# mid-call: tools are serialised ahead of the messages by the chat template, so a
# tool list that shifts between turns invalidates the prefix cache exactly as
# thoroughly as an unstable system prompt would.
