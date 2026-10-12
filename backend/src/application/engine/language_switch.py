"""Mid-call language switching: detection in, one atomic profile swap out.

The recogniser may report what language the caller is actually speaking
(``BaseSttAdapter.detected_language``), and the agent's language rows configure
everything that should follow from it. Wire nothing between the two and a
caller who answers in another tongue gets the half-switched call: an LLM that
follows them (models follow the user), an agent voice that does not, canned
lines in the wrong language, and a turn analyzer consulted about audio it was
never trained on.

:class:`LanguageSwitcher` closes that loop. It sits between the recogniser and
the user aggregator — it must see a final transcript *before* the aggregator
commits it, so the very utterance that confirms a switch is answered under the
new profile — and applies the whole switch at one seam:

* the turn strategy and the silence handler, via their ``apply_profile``
  (their swap semantics — next turn, in-flight deadlines kept — live with
  them, not here);
* the recogniser's language tag, pushed **upstream** as a settings delta,
  which is why this processor must sit directly downstream of it;
* the synthesiser's voice and language, pushed downstream the same way — the
  control frame travels ahead of this turn's transcription, so the reply to
  the confirming utterance is already spoken in the new voice;
* prompt layers 1 and 2, rewritten in place in the shared ``LLMContext``.
  This burns the prefix cache exactly once, deliberately: it is the one-time
  price of the conversation genuinely changing language, paid at the switch
  rather than smeared over every turn.

Two deliberate refusals:

* **Hysteresis.** One borrowed sentence must not flip a call, so the switch
  commits only after ``confirm_utterances`` consecutive qualifying finals
  agree, and one-word utterances — where detection is noisiest — count
  neither way (``min_utterance_words``).
* **Model boundaries.** Services are built once per call. A language row that
  routes to a different recogniser, synthesiser or LLM — or changes anything
  only a rebuild could apply: sample rate, chunking, VAD — is not
  hot-switchable. The switch is refused once, with the exact blockers named in
  the log and reported outward through ``notify``. Per the recogniser
  contract, that is a routing signal for the *next* call, not an error in
  this one.

Backends that never report a language (``reports_language`` false, e.g.
Voxtral) return ``None`` from ``detected_language`` and leave this processor
inert — the capability, not a vendor branch, decides.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    STTUpdateSettingsFrame,
    TranscriptionFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.settings import STTSettings, TTSSettings

from src.application.engine.config import (
    CallContext,
    ResolvedProfile,
    VoiceAgentConfig,
    hot_switch_blockers,
    match_language,
    resolve_profile,
)
from src.application.engine.context.assembly import AgentScript, PromptAssembler

#: Called with a payload describing a switch or a refusal. Optional; the
#: session wires it to its hooks so the worker can persist the event.
SwitchNotifier = Callable[[dict[str, Any]], Awaitable[None]]


class ProfileAware(Protocol):
    """A pipeline component that can adopt another language's profile mid-call."""

    def apply_profile(self, profile: ResolvedProfile) -> None:
        """Switch to `profile`, on the component's own swap semantics."""
        ...


class ReportsDetectedLanguage(Protocol):
    """The one thing the switcher needs from the recogniser."""

    @property
    def detected_language(self) -> str | None:
        """Lowercase code the server reported, or None."""
        ...


class LanguageSwitcher(FrameProcessor):
    """Watches detected language on final transcripts and retargets the call.

    Place it directly between the recogniser and the user aggregator::

        [ transport.input(), stt, switcher, aggregators.user(), ... ]

    Directly downstream of the recogniser, because the STT settings update is
    pushed upstream and must reach it first; upstream of the aggregator,
    because the switch must be in force before the confirming utterance
    commits to the LLM.
    """

    def __init__(
        self,
        *,
        agent: VoiceAgentConfig,
        call: CallContext,
        profile: ResolvedProfile,
        stt: ReportsDetectedLanguage,
        strategy: ProfileAware,
        silence: ProfileAware,
        context,
        assembler: PromptAssembler,
        notify: SwitchNotifier | None = None,
        **kwargs,
    ) -> None:
        """Initialise the switcher.

        Args:
            agent: The organization's agent, supplying the language rows and
                the :class:`~src.application.engine.config.LanguageSwitchPolicy`.
            call: This call's context. Per-call overrides ride along: a support
                override survives a language flip, same as at call start.
            profile: The profile the call started with.
            stt: The recogniser, read for ``detected_language`` per final.
            strategy: The turn stop strategy to re-profile.
            silence: The silence handler to re-profile.
            context: The call's ``LLMContext``, whose stable prefix is
                rewritten in place on a switch.
            assembler: The assembler that produced the context's prefix; its
                layer shape tells the rewrite how many messages to replace.
            notify: Optional callback for switch/refusal events.
            **kwargs: Passed to :class:`FrameProcessor`.
        """
        super().__init__(**kwargs)
        self._agent = agent
        self._call = call
        self._profile = profile
        self._policy = agent.language_switch
        self._stt = stt
        self._strategy = strategy
        self._silence = silence
        self._context = context
        self._assembler = assembler
        self.notify = notify

        self._candidate: str | None = None
        self._streak = 0
        #: Targets already refused against the current profile — logged once,
        #: then silent, or a caller who stays in that language re-logs the same
        #: warning every couple of utterances for the rest of the call.
        self._refused: set[str] = set()
        self._unconfigured_logged: set[str] = set()
        self._switches: list[tuple[str, str]] = []

    # -- public surface ------------------------------------------------------

    @property
    def profile(self) -> ResolvedProfile:
        """The profile currently in force."""
        return self._profile

    @property
    def switches(self) -> list[tuple[str, str]]:
        """Committed switches, oldest first, as (from, to) language codes."""
        return list(self._switches)

    # -- frame handling ------------------------------------------------------

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Observe final transcripts; forward everything untouched."""
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(
            frame, TranscriptionFrame
        ):
            # Before forwarding: if this final confirms the switch, the swap
            # must be in force when the aggregator commits this very utterance.
            await self._observe(frame)
        await self.push_frame(frame, direction)

    async def _observe(self, frame: TranscriptionFrame) -> None:
        detected = self._stt.detected_language
        if not detected:
            return
        if len(frame.text.split()) < self._policy.min_utterance_words:
            # Too short to trust — and too short to reset a pending streak:
            # a "ja" between two German sentences is agreement, not a detour.
            return

        target = self._target_for(detected)
        if target is None:
            if detected not in self._unconfigured_logged:
                self._unconfigured_logged.add(detected)
                logger.info(
                    f"language: caller detected as {detected!r} but the agent has no "
                    f"row for it; staying on {self._profile.language!r}"
                )
            self._candidate, self._streak = None, 0
            return

        if target == self._profile.language:
            self._candidate, self._streak = None, 0
            return

        if target == self._candidate:
            self._streak += 1
        else:
            self._candidate, self._streak = target, 1

        if self._streak < self._policy.confirm_utterances:
            return
        if target in self._refused:
            return
        await self._switch(target)

    def _target_for(self, detected: str) -> str | None:
        """Resolve a detected code to a switchable language, or None.

        A configured language row first; failing that, the agent's default —
        so a call that switched away can switch back even though the default
        usually has no row of its own.
        """
        key = match_language(self._agent.languages, detected)
        if key is not None:
            return key
        default = self._agent.default_language.strip().lower().replace("_", "-")
        code = detected.strip().lower().replace("_", "-")
        if code == default or code.split("-")[0] == default.split("-")[0]:
            return default
        return None

    # -- the switch ----------------------------------------------------------

    async def _switch(self, target: str) -> None:
        call = self._call.model_copy(update={"language": target})
        new = resolve_profile(self._agent, call)

        blockers = hot_switch_blockers(self._profile, new)
        if blockers:
            self._refused.add(target)
            logger.warning(
                f"language switch {self._profile.language}→{new.language} refused: "
                + "; ".join(blockers)
            )
            await self._emit(
                {
                    "event": "language_switch_refused",
                    "from": self._profile.language,
                    "to": new.language,
                    "blockers": blockers,
                }
            )
            return

        old = self._profile
        self._profile = new
        self._call = call

        self._strategy.apply_profile(new)
        self._silence.apply_profile(new)
        self._rewrite_prompt_layers(new)
        # Upstream to the recogniser: keeps its frame tags (and any hint it
        # sends) in step. Downstream to the synthesiser: voice and language for
        # every chunk from here on, starting with this turn's reply.
        await self.push_frame(
            STTUpdateSettingsFrame(delta=STTSettings(language=new.stt.language)),
            FrameDirection.UPSTREAM,
        )
        await self.push_frame(
            TTSUpdateSettingsFrame(
                delta=TTSSettings(voice=new.tts.voice, language=new.language)
            )
        )

        self._candidate, self._streak = None, 0
        # Refusals were judged against the old profile; a new baseline re-opens them.
        self._refused.clear()
        self._switches.append((old.language, new.language))
        logger.info(f"language switch {old.language}→{new.language} | {new.summary()}")
        await self._emit(
            {
                "event": "language_switched",
                "from": old.language,
                "to": new.language,
                "profile": new.summary(),
            }
        )

    def _rewrite_prompt_layers(self, new: ResolvedProfile) -> None:
        """Replace layers 1–2 in place, leaving the conversation untouched."""
        customer = self._assembler.profile
        if customer is not None:
            customer = replace(customer, language=new.language)
        assembler = PromptAssembler(
            AgentScript(
                system_prompt=new.prompts.system_prompt, script=new.prompts.call_script
            ),
            customer,
        )

        old_len = len(self._assembler.stable_prefix())
        messages = self._context.messages
        if len(messages) < old_len or (
            messages and messages[0].get("role") != "system"
        ):
            logger.warning(
                "language switch: context does not start with the expected stable "
                "prefix; prompt layers left as they were"
            )
            return
        # Same customer presence on both sides, so the prefixes are the same
        # length and the slice cannot swallow conversation history.
        messages[:old_len] = assembler.stable_prefix()
        self._assembler = assembler

    async def _emit(self, payload: dict[str, Any]) -> None:
        """Report an event, and never let the reporter break the call."""
        if self.notify is None:
            return
        try:
            await self.notify(payload)
        except Exception as exc:  # noqa: BLE001 - notifier is caller-supplied
            logger.warning(f"language switch: notify failed: {exc}")
