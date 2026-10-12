"""Deferred SMS dispatch (VOAD-60).

The agent's "send_sms" tool no longer sends anything itself — the model
merely marks that it decided, during the call, that the pre-written message
should go out. The actual send happens once the call has fully ended
(``CallSession.run``), never mid-conversation. This mirrors how ``end_call``
defers the real hangup to ``CallEndGate`` at the pipeline tail, just without
a pipeline stage of its own: there is no audio to wait on, only "the call is
over now" — a plain flag the session checks in its `finally` block is enough.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SmsIntent:
    """Whether the agent decided, during the call, to send the configured SMS."""

    requested: bool = False

    def mark_requested(self) -> None:
        self.requested = True
