"""VOAD-27: the connect-reset and feedback-request timers.

``ConnectAndFeedbackSilenceHandler`` layers two more specific behaviours on
top of the base ``SilenceHandler`` cascade (see test_silence.py for that):

* the *caller* staying silent, past ``reset_timeout_seconds``, ends the call
  outright with no goodbye spoken — counting only from connect or from the
  end of our own greeting, never reset by our own speech (see
  ``test_agents_own_greeting_does_not_count_as_the_caller_speaking`` below);
* silence after the agent's most recent reply, past ``feedback_delay_seconds``,
  speaks the organization's ``spoken_feedback_request`` phrase (rendered with
  the caller's name) once, then falls back to the base reprompt/goodbye
  cascade if the caller still says nothing.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndWorkerFrame,
    Frame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from src.application.engine.silence import ConnectAndFeedbackSilenceHandler
from tests.engine.conftest import make_profile


def build_handler(
    *,
    feedback_request: str = "",
    no_answer: str = "",
    client_name: str = "",
    **kwargs,
) -> tuple[ConnectAndFeedbackSilenceHandler, list[Frame]]:
    profile = make_profile()
    profile = profile.model_copy(
        update={
            "spoken": profile.spoken.model_copy(
                update={"feedback_request": feedback_request, "no_answer": no_answer}
            )
        }
    )
    handler = ConnectAndFeedbackSilenceHandler(
        profile=profile,
        prompt_seconds=0,
        reset_timeout_seconds=0,
        feedback_delay_seconds=0,
        client_name=client_name,
        **kwargs,
    )
    pushed: list[Frame] = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    handler.push_frame = collect  # type: ignore[method-assign]

    # Tests drive `_wait_and_prompt`/`_wait_and_reset` directly; a frame that
    # triggers the base class's own `_restart_timer` (e.g. BotStoppedSpeaking)
    # must not *also* spawn a real background timer task racing the explicit
    # call below — neutralize scheduling, not just frame pushing.
    def noop_create_task(coro):
        coro.close()

    handler.create_task = noop_create_task  # type: ignore[method-assign]
    return handler, pushed


async def test_connect_silence_ends_the_call_with_no_goodbye():
    """The caller has never spoken (voicemail, dead air): reset_timeout_seconds
    ends the call outright — no goodbye, unlike the base cascade's hangup."""
    handler, pushed = build_handler()

    await handler._wait_and_prompt()

    assert not any(isinstance(f, TTSSpeakFrame) for f in pushed)
    assert any(isinstance(f, EndWorkerFrame) for f in pushed)


async def test_agents_own_greeting_does_not_count_as_the_caller_speaking():
    """Regression: with greet_first (the outbound default), the agent speaks
    before the caller ever does. Its greeting must not count as "someone has
    spoken" — otherwise reset_timeout_seconds could never fire again for the
    rest of the call, and a line that connected to voicemail would sit in the
    slower prompt/max_prompts cascade instead of ending via this timeout."""
    handler, pushed = build_handler()

    await handler.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await handler.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert handler._user_ever_spoken is False

    await handler._wait_and_prompt()

    assert not any(isinstance(f, TTSSpeakFrame) for f in pushed)
    assert any(isinstance(f, EndWorkerFrame) for f in pushed)


async def test_no_answer_configured_repeats_it_before_hanging_up():
    """With spoken_no_answer set, the caller-never-spoke timeout repeats that
    line (instead of silently hanging up) until max_no_answer_prompts."""
    handler, pushed = build_handler(
        no_answer="Hello? Anyone there?", max_no_answer_prompts=2
    )

    await handler._wait_and_prompt()
    assert [f.text for f in pushed if isinstance(f, TTSSpeakFrame)] == [
        "Hello? Anyone there?"
    ]
    assert handler._no_answer_prompts_sent == 1
    assert not any(isinstance(f, EndWorkerFrame) for f in pushed)

    await handler._wait_and_prompt()
    assert [f.text for f in pushed if isinstance(f, TTSSpeakFrame)] == [
        "Hello? Anyone there?",
        "Hello? Anyone there?",
    ]
    assert handler._no_answer_prompts_sent == 2
    assert not any(isinstance(f, EndWorkerFrame) for f in pushed)

    await handler._wait_and_prompt()
    prompts = [f.text for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert prompts == ["Hello? Anyone there?", "Hello? Anyone there?"]
    assert any(isinstance(f, EndWorkerFrame) for f in pushed)


async def test_caller_speaking_stops_the_no_answer_cascade():
    """The caller speaking at any point during the no-answer cascade cancels
    it, same as it does for the base mid-conversation cascade."""
    handler, _pushed = build_handler(no_answer="Hello? Anyone there?")

    await handler._wait_and_prompt()
    assert handler._no_answer_prompts_sent == 1

    from pipecat.frames.frames import UserStartedSpeakingFrame

    await handler.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert handler._user_ever_spoken is True


async def test_feedback_delay_speaks_the_rendered_phrase_once():
    """Past feedback_delay_seconds after a reply, the configured phrase is
    spoken with the caller's name substituted in, counting as a prompt."""
    handler, pushed = build_handler(
        feedback_request="{{ name }}, are you still with me?", client_name="Ivan"
    )
    handler._user_ever_spoken = True

    await handler._wait_and_prompt()

    prompts = [f for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert [p.text for p in prompts] == ["Ivan, are you still with me?"]
    assert handler._feedback_sent is True
    assert handler.prompts_sent == 1


async def test_feedback_sent_at_most_once_per_silence_episode():
    """A second silent tick without the caller speaking again falls back to
    the base reprompt instead of repeating the feedback line."""
    handler, pushed = build_handler(
        feedback_request="{{ name }}, still there?", client_name="Ivan"
    )
    handler._user_ever_spoken = True
    handler._feedback_sent = True

    await handler._wait_and_prompt()

    prompts = [f for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert [p.text for p in prompts] == [handler._profile.spoken.silence]


async def test_no_configured_phrase_falls_back_to_base_reprompt():
    """An organization that never set spoken_feedback_request sees the
    class behave exactly like the base handler mid-conversation."""
    handler, pushed = build_handler()
    handler._user_ever_spoken = True

    await handler._wait_and_prompt()

    prompts = [f for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert [p.text for p in prompts] == [handler._profile.spoken.silence]
    assert handler.prompts_sent == 1
