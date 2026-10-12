"""One call, start to finish.

A session is the unit the worker owns: give it an organization's agent
configuration, a call context and a transport, and it runs until the caller
hangs up, the leg goes idle, or it is cancelled. It is the voice equivalent of
the chat service's ``Chatter`` — the place where per-organization configuration
becomes a running conversation.

Deliberately free of infrastructure. No database session, no Redis, no Kafka:
those belong to the worker that constructs this. What the outside world needs
back — transcripts, outcomes, metrics — arrives through :class:`SessionHooks`,
so persistence can change without the engine noticing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pipecat.frames.frames import EndFrame, LLMRunFrame
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from src.application.engine.audio import ASR_SAMPLE_RATE, AudioPath
from src.application.engine.config import (
    CallContext,
    ResolvedProfile,
    VoiceAgentConfig,
    resolve_profile,
)
from src.application.engine.pipeline import (
    BuiltPipeline,
    PipelineTaps,
    SmsSender,
    build_pipeline,
)

#: Called with the call id and an event payload. Anything the worker wants to
#: persist — a final transcript, a turn's latency, the outcome — arrives here.
EventHook = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class SessionHooks:
    """Where a session reports to. Every hook is optional."""

    on_started: EventHook | None = None
    on_transcript: EventHook | None = None
    on_finished: EventHook | None = None
    #: A mid-call language switch, or a refused one. The payload carries
    #: ``event`` ("language_switched" / "language_switch_refused"), ``from``,
    #: ``to``, and either the new profile summary or the blockers.
    on_language_switch: EventHook | None = None
    #: One payload per turn from the latency observer: the stage durations the
    #: summary log line prints, as data (``waiting_user_ms``, ``stt_ms``,
    #: ``ttt_ms``, ``tts_ms``, ``voice_to_voice_ms``, …).
    on_turn_timing: EventHook | None = None

    async def emit(
        self, hook: EventHook | None, call_id: str, payload: dict[str, Any]
    ) -> None:
        """Call a hook, and never let its failure end the call.

        A broken metrics sink is not a reason to hang up on a customer.

        Args:
            hook: The hook to call, or None.
            call_id: Correlation id passed through to the hook.
            payload: Event body.
        """
        if hook is None:
            return
        try:
            await hook(call_id, payload)
        except Exception as exc:  # noqa: BLE001 - hooks are caller-supplied
            logger.warning(
                f"call {call_id}: hook {getattr(hook, '__name__', hook)!r} failed: {exc}"
            )


@dataclass(slots=True)
class CallSession:
    """Runs one call against one organization's configuration."""

    agent: VoiceAgentConfig
    call: CallContext
    transport: BaseTransport
    hooks: SessionHooks = field(default_factory=SessionHooks)
    #: Extra processors the transport's edge wants in the pipeline — the
    #: playground's caption taps. None for a phone leg.
    taps: PipelineTaps | None = None
    #: Sender the "send_sms" tool calls into, when the agent enables it. None
    #: leaves the tool off — the worker is the only caller with a database
    #: session to build one from.
    send_sms: SmsSender | None = None
    handle_sigint: bool = False

    profile: ResolvedProfile | None = None
    _built: BuiltPipeline | None = None

    def prepare(self) -> ResolvedProfile:
        """Resolve the profile and build the pipeline, without running anything.

        Split from :meth:`run` so a caller can inspect what a call *would* do —
        which is what the diagnostics command and the readiness check want, and
        what makes a misconfiguration visible before a customer hears silence.

        Returns:
            The resolved profile this session will run with.
        """
        self.profile = resolve_profile(self.agent, self.call)
        log = logger.bind(call_id=self.call.call_id, org_uuid=self.call.org_uuid)
        log.info(f"call start | {self.profile.summary()}")

        self._built = build_pipeline(
            profile=self.profile,
            call=self.call,
            transport=self.transport,
            audio_path=AudioPath(asr_sample_rate=ASR_SAMPLE_RATE),
            agent=self.agent,
            taps=self.taps,
            send_sms=self.send_sms,
        )
        if self._built.language_switcher is not None:
            self._built.language_switcher.notify = self._report_language_switch
        self._built.latency.notify = self._report_turn_timing
        # The recogniser's own caveats, not a generic banner: two backends on the
        # same route assume different things about a protocol neither specifies.
        if self._built.stt.protocol_assumptions:
            log.info(
                f"{type(self._built.stt).__name__} protocol assumptions in force: "
                + "; ".join(self._built.stt.protocol_assumptions)
            )
        return self.profile

    async def run(self) -> None:
        """Run the call until the transport closes or the pipeline goes idle."""
        if self._built is None or self.profile is None:
            self.prepare()
        built, profile = self._built, self.profile
        log = logger.bind(call_id=self.call.call_id, org_uuid=self.call.org_uuid)

        @self.transport.event_handler("on_client_connected")
        async def _on_connected(_transport, _client):
            log.info("caller connected")
            await self.hooks.emit(
                self.hooks.on_started,
                self.call.call_id,
                {"profile": profile.summary(), "org_uuid": self.call.org_uuid},
            )
            if profile.greet_first and profile.prompts.greeting_kickoff:
                # The context so far is system-only, and many OpenAI-compatible
                # gateways reject a completion with no user turn — LiteLLM
                # answers "No user query found in messages" and the agent never
                # opens its mouth. The kickoff gives them one, in layer 3, so
                # the cacheable prefix is untouched.
                built.context.add_message(
                    {"role": "user", "content": profile.prompts.greeting_kickoff}
                )
                await built.task.queue_frames([LLMRunFrame()])

        @self.transport.event_handler("on_client_disconnected")
        async def _on_disconnected(_transport, _client):
            log.info("caller disconnected")
            await built.task.cancel()

        @built.task.event_handler("on_idle_timeout")
        async def _on_idle_timeout(_task):
            log.warning(
                f"call ending: idle timeout after {profile.idle_timeout_seconds}s "
                "with no bot or caller speech activity"
            )

        # A finished call's pipeline is a web of reference cycles (processors
        # link both ways, handlers close over their owners), so only a full
        # collection frees it — and a process carrying calls rarely runs one
        # on its own: twelve calls in, not one graph had been reclaimed, each
        # holding its buffers and provider clients. This runs after the
        # pipeline stops but while this session still holds it, so it
        # reclaims the calls before this one. Cheap only because the hooks
        # and API lifespans ``gc.freeze()`` the startup heap.
        runner = WorkerRunner(handle_sigint=self.handle_sigint, force_gc=True)
        try:
            await runner.run(built.task)
        finally:
            await self.hooks.emit(
                self.hooks.on_finished,
                self.call.call_id,
                {
                    "messages": built.context.get_messages(),
                    "org_uuid": self.call.org_uuid,
                },
            )
            # VOAD-60: the SMS tool only ever marks intent mid-call — the
            # actual send happens here, once, after the call has genuinely
            # ended (however it ended), never while it was still live.
            if (
                built.sms_intent is not None
                and built.sms_intent.requested
                and self.send_sms is not None
            ):
                try:
                    await self.send_sms(self.agent.sms_tool_message)
                except Exception as exc:  # noqa: BLE001 - never let this break call teardown
                    log.warning(f"deferred SMS send failed: {exc}")
            log.info("call finished")

    async def _report_language_switch(self, payload: dict[str, Any]) -> None:
        """Forward a switch (or refusal) to whoever is listening."""
        await self.hooks.emit(self.hooks.on_language_switch, self.call.call_id, payload)

    async def _report_turn_timing(self, payload: dict[str, Any]) -> None:
        """Forward one turn's latency breakdown to whoever is listening."""
        await self.hooks.emit(self.hooks.on_turn_timing, self.call.call_id, payload)

    async def hangup(self) -> None:
        """End the call politely: let queued audio drain, then stop.

        For an operator pressing "end call", or a campaign being cancelled.
        """
        if self._built is not None:
            await self._built.task.queue_frames([EndFrame()])

    async def cancel(self) -> None:
        """Stop immediately, without draining. For shutdown and for errors."""
        if self._built is not None:
            await self._built.task.cancel()
