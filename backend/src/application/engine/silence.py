"""VOAD-27: connect-timeout reset and feedback-request delay, on top of the
base silence handler (``src.application.engine.turn.silence.SilenceHandler``).

The base handler already runs one cascade — ``prompt_seconds`` of silence
speaks the localised "are you still there" line, ``max_prompts`` unanswered
ones say goodbye and end the call — and it runs that cascade from the moment
``StartFrame`` arrives, with no distinction between "nobody has said a word
since we picked up" and "we were mid-conversation and it went quiet". VOAD-27
asks for two more specific behaviours instead of, and layered on, that one:

* ``reset_timeout_seconds`` — the *caller* staying silent for this long,
  counted from connect (or from the end of our own greeting, whichever is
  later — see below), repeats ``SpokenPrompts.no_answer`` (if the
  organization has set one) up to ``max_no_answer_prompts`` times, then ends
  the call outright with no goodbye spoken: there is nobody there to say it
  to (voicemail, a leg that connected to dead air). An organization that has
  not set ``no_answer`` gets the original behaviour unchanged: a single
  silent wait, then hangup, no line spoken. This is deliberately a
  *different* threshold from ``prompt_seconds``/``max_prompts``, which the
  docstring on ``SilencePolicy`` says applies mid-conversation.

  Only the caller's own speech counts as "spoken" for this timer — the
  agent's greeting does not, even though ``VoiceAgentConfig.greet_first``
  defaults to ``True`` for every outbound call (``config.py``'s
  ``resolve_profile``) and so almost every real call has the agent talking
  first. Counting the agent's own greeting as "someone has spoken" would
  make this timer fire at most once, on the very first connect, and never
  again for the rest of the call — silently defeating the one thing it
  exists to detect (a line that connected but nobody ever actually
  answered). Tracked via ``_user_ever_spoken``, set only by
  ``UserStartedSpeakingFrame``.
* ``feedback_delay_seconds`` — silence held for this long after the agent's
  most recent reply speaks the organization's feedback-request phrase
  (``VoiceAgent.spoken_feedback_request``, rendered with the caller's name
  via ``utils.script.render_script``) *instead of* the base class's generic
  reprompt, once, before falling back to the normal reprompt/goodbye cascade
  if the caller still says nothing. Chosen over "in addition to": the two
  timers would otherwise race independently off the same
  ``BotStoppedSpeakingFrame`` trigger point, and with the schema's own
  defaults (``prompt_seconds=9``, ``feedback_delay_seconds=15``) the base
  cascade would already be mid-goodbye by the time the feedback timer fired,
  so "in addition to" would in practice mean "hardly ever". Replacing the
  *next* reprompt slot with the feedback ask, once, keeps a single timer and
  a single voice active at a time, and still degrades to the base behaviour
  (and eventual hangup) if the feedback line goes unanswered too. If the
  organization has not configured a phrase, this class is a no-op layered
  on top of ``prompt_seconds``/``max_prompts`` mid-conversation — unchanged.

This does not touch ``turn/silence.py`` — it *extends* it, per the class's
own module docstring, by overriding the one hook (``_wait_and_prompt``) that
decides what a fired timer means, and by tracking one extra bit of state
(whether the caller has ever spoken). Everything else — the timer scheduling, the
goodbye/hangup mechanics, the "caller started talking, cancel everything"
resets — is inherited unchanged, so a call whose agent has not set the two
new ``SilencePolicy`` fields (they carry defaults) or a
``spoken_feedback_request`` behaves exactly as before.

Wired into the running pipeline at ``pipeline.py`` (search for
``ConnectAndFeedbackSilenceHandler``), which passes
``profile.silence.reset_timeout_seconds``, ``profile.silence.
feedback_delay_seconds`` and the caller's name (``call.customer.name``) at
construction — every live call already builds this class, not the plain
``SilenceHandler``.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from pipecat.frames.frames import Frame, TTSSpeakFrame, UserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.config import ResolvedProfile
from src.application.engine.turn.silence import SilenceHandler
from src.utils.script import ScriptError, render_script


class ConnectAndFeedbackSilenceHandler(SilenceHandler):
    """``SilenceHandler`` plus the connect-reset and feedback-request timeouts.

    See the module docstring for the behaviour and why it is layered this way
    rather than as a second, independent timer.
    """

    def __init__(
        self,
        *,
        profile: ResolvedProfile,
        prompt_seconds: float = 9.0,
        max_prompts: int = 2,
        reset_timeout_seconds: float = 20.0,
        max_no_answer_prompts: int = 2,
        feedback_delay_seconds: float = 15.0,
        client_name: str = "",
        **kwargs,
    ) -> None:
        """Initialise the handler.

        Args:
            profile: Language profile supplying the localised prompt/goodbye
                (base class), the no-answer line and the feedback-request
                template (this class).
            prompt_seconds: Silence to tolerate before the base class's
                mid-conversation reprompt. Unchanged meaning.
            max_prompts: Unanswered mid-conversation prompts before hanging
                up. Unchanged meaning.
            reset_timeout_seconds: How long the caller may stay silent —
                counted from connect, or from the end of our own last turn,
                whichever comes later — before repeating
                ``SpokenPrompts.no_answer`` (or, if unset, ending the call
                with no goodbye). Our own speech never counts against this;
                only the caller's does.
            max_no_answer_prompts: Unanswered ``no_answer`` prompts before
                giving up and hanging up. Irrelevant if the organization has
                not set ``SpokenPrompts.no_answer``.
            feedback_delay_seconds: Silence tolerated after the agent's most
                recent reply before asking for feedback instead of repeating
                the generic reprompt.
            client_name: The caller's name, for rendering the feedback
                template. Empty renders whatever the template does with an
                empty ``name`` (typically just omitting it).
            **kwargs: Passed to :class:`SilenceHandler`.
        """
        super().__init__(
            profile=profile,
            prompt_seconds=prompt_seconds,
            max_prompts=max_prompts,
            **kwargs,
        )
        self._reset_timeout_seconds = reset_timeout_seconds
        self._max_no_answer_prompts = max_no_answer_prompts
        self._feedback_delay_seconds = feedback_delay_seconds
        self._client_name = client_name
        self._feedback_phrase = self._render_feedback_phrase(profile)
        #: "Алё?"-style prompts spoken while the caller has never answered at
        #: all. Separate from the base class's ``_prompts_sent``, which only
        #: counts mid-conversation reprompts.
        self._no_answer_prompts_sent = 0

        # True once the CALLER has produced a single frame of speech — the
        # agent's own greeting deliberately does not set this (see the module
        # docstring): with greet_first defaulting to True, counting our own
        # speech here would make this flip to True on every outbound call's
        # first turn, permanently disabling the "caller never answered"
        # detection it exists for. Distinguishes "the caller has never said
        # anything" (-> reset_timeout_seconds, re-armed after every one of
        # our turns) from "the caller has spoken at least once, now it's
        # quiet again" (-> prompt_seconds, or the feedback ask once, then
        # prompt_seconds again).
        self._user_ever_spoken = False
        # Whether the feedback line has already been used for the current
        # silence episode; reset the moment the caller speaks again, so a
        # long call is asked for feedback at most once per gap, not on every
        # feedback_delay_seconds tick.
        self._feedback_sent = False

    def apply_profile(self, profile: ResolvedProfile) -> None:
        """Switch to another language's prompts (and re-render the feedback line)."""
        super().apply_profile(profile)
        self._feedback_phrase = self._render_feedback_phrase(profile)

    def set_client_name(self, client_name: str) -> None:
        """Update the caller's name and re-render the feedback line with it."""
        self._client_name = client_name
        self._feedback_phrase = self._render_feedback_phrase(self._profile)

    def _render_feedback_phrase(self, profile: ResolvedProfile) -> str:
        """The feedback line to speak, or "" if unconfigured/unrenderable.

        Deliberately never returns a rendered *empty* template as something
        to speak: an empty ``spoken_feedback_request`` means the organization
        has not opted in, and a template that fails to render is logged and
        treated the same way rather than crashing pipeline construction or
        speaking a broken line to a live caller.
        """
        template = profile.spoken.feedback_request
        if not template:
            return ""
        try:
            phrase = render_script(template, name=self._client_name)
        except ScriptError as exc:
            logger.warning(
                f"silence: spoken_feedback_request failed to render, disabling it: {exc}"
            )
            return ""
        return phrase

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Track whether the caller has ever spoken, then defer to the base class."""
        if isinstance(frame, UserStartedSpeakingFrame):
            if not self._user_ever_spoken:
                logger.debug(
                    "silence: caller spoke for the first time, disabling the "
                    f"{self._reset_timeout_seconds}s reset_timeout_seconds watchdog "
                    "for the rest of the call (VOAD-27)"
                )
            self._user_ever_spoken = True
            self._feedback_sent = False
        await super().process_frame(frame, direction)

    # -- the one hook this class changes ------------------------------------

    async def _wait_and_prompt(self) -> None:
        """Route a fired timer to reset, feedback, or the base reprompt.

        Called by the base class's own ``_restart_timer`` via
        ``self.create_task(self._wait_and_prompt())`` — overriding it here is
        enough to change what a firing timer means, with no change to how or
        when it is scheduled/cancelled.
        """
        if not self._user_ever_spoken:
            await self._wait_and_reset()
            return
        if self._feedback_phrase and not self._feedback_sent:
            await self._wait_and_ask_feedback()
            return
        await super()._wait_and_prompt()

    async def _wait_and_reset(self) -> None:
        """The caller has never spoken, past ``reset_timeout_seconds``.

        Repeats ``SpokenPrompts.no_answer`` (if configured) up to
        ``max_no_answer_prompts`` times, then ends the call. An organization
        that has not set ``no_answer`` keeps the original behaviour: this
        fires once and ends the call silently, no line spoken.
        """
        await asyncio.sleep(self._reset_timeout_seconds)
        self._timer = None

        if (
            self._user_ever_spoken
            or self._user_speaking
            or self._bot_speaking
            or self._closing
        ):
            return

        phrase = self._profile.spoken.no_answer
        if phrase and self._no_answer_prompts_sent < self._max_no_answer_prompts:
            self._no_answer_prompts_sent += 1
            logger.info(
                f"silence: caller never spoke, {self._reset_timeout_seconds}s since our "
                f"last turn, prompting ({self._no_answer_prompts_sent}/"
                f"{self._max_no_answer_prompts})"
            )
            await self.push_frame(TTSSpeakFrame(phrase))
            # No timer restart here, matching the base class: BotStoppedSpeaking
            # (from this TTS actually playing) restarts it once the line has
            # been spoken, via the inherited process_frame/_restart_timer path.
            return

        logger.info(
            f"silence: caller never spoke, {self._reset_timeout_seconds}s since our last "
            "turn, ending the call (VOAD-27 reset_timeout_seconds)"
        )
        # No goodbye: the caller has never said a word (voicemail, dead air,
        # a handset put down before we finished greeting), and speaking
        # further into that silence is exactly the cost this timeout exists
        # to avoid. `_end_call` requires `_closing` set first.
        self._closing = True
        await self._end_call()

    async def _wait_and_ask_feedback(self) -> None:
        """Silence after a reply, past ``feedback_delay_seconds``: ask for feedback."""
        await asyncio.sleep(self._feedback_delay_seconds)
        self._timer = None

        if (
            self._user_speaking
            or self._bot_speaking
            or self._closing
            or self._awaiting_response
        ):
            return

        self._feedback_sent = True
        # Counts toward max_prompts like a normal reprompt would, so a call
        # that gets the feedback ask and then keeps hearing nothing still
        # reaches the base class's goodbye/hangup instead of staying open
        # indefinitely.
        self._prompts_sent += 1
        logger.info(
            f"silence: no reply for {self._feedback_delay_seconds}s after the agent's "
            "last turn, asking for feedback instead of the generic reprompt"
        )
        await self.push_frame(TTSSpeakFrame(self._feedback_phrase))
        # No timer restart here, matching the base class: BotStoppedSpeaking
        # (from this TTS actually playing) restarts it once the line has been
        # spoken, via the inherited process_frame/_restart_timer path.
