"""Names for the campaign layer — the machinery *around* calls, not inside them.

``CallStatusEnum`` (``enums.engine``) stays the vocabulary of one attempt/leg;
these are the lifecycles above it: a campaign's, and a call-as-assignment's,
which spans every attempt made for it.
"""

from enum import StrEnum


class CallOutcomeEnum(StrEnum):
    """The business result of a conversation, distinct from the technical
    attempt status. Assigned by post-call analysis (``services/analysis.py``);
    ``no_answer`` (telephony) and ``sms_sent`` (a delivered/sent ``Message``)
    are the exceptions — derived, no LLM involved.
    """

    interested = "interested"
    not_interested = "not_interested"
    call_later = "call_later"
    converted = "converted"
    escalated = "escalated"
    answerphone = "answerphone"
    wrong_number = "wrong_number"
    do_not_call = "do_not_call"
    no_answer = "no_answer"
    #: The agent sent the customer an SMS during the call (VOAD-80). Derived
    #: from a ``Message`` row, never predicted by the LLM, and it overwrites
    #: any analysis outcome except ``do_not_call``.
    sms_sent = "sms_sent"


class SentimentEnum(StrEnum):
    """The tone of a meaningful conversation, assigned by post-call analysis."""

    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class ReasonCategoryEnum(StrEnum):
    """Why a ``not_interested`` conversation ended that way."""

    bonus_conditions = "bonus_conditions"
    payment_problem = "payment_problem"
    lost_interest = "lost_interest"
    competitor = "competitor"
    technical_issue = "technical_issue"
    responsible_gaming = "responsible_gaming"
    other = "other"


class ClientStatusEnum(StrEnum):
    """Whether a client may be dialed. Anything but ``active`` is refused at
    upload, at originate, and again by the dispatcher at claim time."""

    active = "active"
    do_not_call = "do_not_call"
    blocked = "blocked"


class ClientSegmentEnum(StrEnum):
    """A client's lead temperature, distinct from :class:`ClientStatusEnum`
    (which gates whether the client may be dialed at all). Assigned by a
    status-column CSV import (VOAD-32); has no bearing on ``do_not_call``."""

    cold = "cold"
    warm = "warm"
    hot = "hot"


class CampaignStatusEnum(StrEnum):
    """Where a campaign is in its life. Operators drive it; the dispatcher
    moves ``scheduled → running`` and ``running → completed`` on its own,
    and can also move a campaign to ``error`` when its setup becomes
    undialable at runtime (VOAD-36) — distinct from ``paused``, which is an
    operator's deliberate choice."""

    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    paused = "paused"
    completed = "completed"
    error = "error"


class CallLifecycleEnum(StrEnum):
    """One call-as-assignment across all of its attempts.

    ``calling`` means an attempt exists that has not settled yet; the
    dispatcher settles it back to ``pending`` (retry scheduled) or forward to
    a terminal state. ``exhausted`` is "we tried, per policy, and never got a
    conversation" — distinct from ``completed``, which means one happened.
    """

    pending = "pending"
    calling = "calling"
    completed = "completed"
    exhausted = "exhausted"
    canceled = "canceled"
    #: The client is flagged do-not-call; the dispatcher refuses to touch it.
    blocked = "blocked"
