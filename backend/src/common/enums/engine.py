"""Names the engine dispatches on.

Every one of these is stored on an organization's rows and looked up in a
registry at call time — see `src/integrations/*/base.py`. Adding a backend is a
value here, an adapter module, and a row; never a change inside the engine.
"""

from enum import StrEnum


class ProviderKindEnum(StrEnum):
    """Which side of the pipeline a provider serves."""

    stt = "stt"
    tts = "tts"
    ttt = "ttt"


class SttAdapterEnum(StrEnum):
    """Speech-to-text clients."""

    qwen3_asr = "qwen3_asr"
    voxtral = "voxtral"
    cartesia = "cartesia"
    deepgram = "deepgram"
    openrouter = "openrouter"


class TtsAdapterEnum(StrEnum):
    """Text-to-speech clients."""

    qwen3_tts = "qwen3_tts"
    cartesia = "cartesia"
    deepgram = "deepgram"
    openrouter = "openrouter"


class TttAdapterEnum(StrEnum):
    """Text-to-text (LLM) clients."""

    openai_compatible = "openai_compatible"


class VadAdapterEnum(StrEnum):
    """Voice activity detectors. In-process, no endpoint."""

    silero = "silero"


class TelephonyAdapterEnum(StrEnum):
    """Telephony legs — who carries the call's audio to and from the phone network.

    Chosen per organization like every other provider: a paid carrier with its
    own media protocol (``twilio``), a self-hosted jambonz stack speaking its
    ``listen`` verb (``jambonz``), or a generic self-hosted SIP service
    fronted by the bridge contract (``sip_bridge``).
    """

    twilio = "twilio"
    jambonz = "jambonz"
    sip_bridge = "sip_bridge"


class MessagingAdapterEnum(StrEnum):
    """Messaging backends — who delivers an SMS to a handset.

    Deliberately its own axis rather than a method on the telephony leg: the
    trunk that carries audio and the route that carries text are priced,
    provisioned and regulated separately, and a self-hosted SIP bridge carries
    no SMS at all. One organization can therefore keep its calls on a bridge
    and its messages on a carrier, which is the common arrangement.
    """

    twilio = "twilio"
    mamonty = "mamonty"


class TurnAnalyzerEnum(StrEnum):
    """End-of-turn classifiers consulted by the turn controller."""

    none = "none"
    smart_turn_v3 = "smart_turn_v3"


class ChunkingModeEnum(StrEnum):
    """How a reply is cut up on its way to TTS.

    ``clause`` speaks the first clause while the model is still generating, and
    is what keeps time-to-first-audio under a second. ``whole_turn`` waits for
    the complete reply and synthesises it in one request: one draw of the
    speaker, so the voice cannot drift mid-answer, paid for in latency.
    """

    clause = "clause"
    whole_turn = "whole_turn"


class CallDirectionEnum(StrEnum):
    """Who placed the call. Decides whether the agent speaks first."""

    inbound = "inbound"
    outbound = "outbound"


class CallStatusEnum(StrEnum):
    """Where a call is in its life, as campaign logic needs to see it.

    Coarser than SIP: a retry policy cares whether the callee was busy, absent,
    or spoken to — not which of three provisional responses preceded that.
    """

    queued = "queued"
    dialing = "dialing"
    in_progress = "in_progress"
    completed = "completed"
    busy = "busy"
    no_answer = "no_answer"
    failed = "failed"
    canceled = "canceled"
    #: The callee declined the call (SIP 603 and kin). Retried like no_answer.
    rejected = "rejected"
    #: The number does not exist / is unroutable (SIP 404/484). Never retried.
    invalid_number = "invalid_number"


class MessageStatusEnum(StrEnum):
    """Where an outbound SMS is in its life.

    Coarser than any one vendor's vocabulary, and ordered: a status callback
    may only move a message **forward** through this list. Carriers deliver
    dispositions out of order often enough that "sent" arriving after
    "delivered" is routine, not an anomaly, and the later write must lose.

    The distinction that matters operationally is ``undelivered`` vs
    ``failed``: the carrier accepted the message and could not deliver it
    (handset off, number dead) vs the provider never got it off the ground
    (no route, blocked, bad sender). One is the destination's problem, the
    other is the configuration's.
    """

    #: Accepted by us, not yet handed to the provider.
    queued = "queued"
    #: The provider accepted it; no carrier verdict yet.
    sent = "sent"
    #: The handset acknowledged it.
    delivered = "delivered"
    #: The carrier tried and gave up.
    undelivered = "undelivered"
    #: Never left the provider.
    failed = "failed"
    #: Withdrawn before delivery.
    canceled = "canceled"


#: How far along each status is. A disposition may only raise a message's
#: rank, which is what makes out-of-order callbacks harmless.
MESSAGE_STATUS_RANK: dict[MessageStatusEnum, int] = {
    MessageStatusEnum.queued: 0,
    MessageStatusEnum.sent: 1,
    MessageStatusEnum.delivered: 2,
    MessageStatusEnum.undelivered: 2,
    MessageStatusEnum.failed: 2,
    MessageStatusEnum.canceled: 2,
}


class SmsMessageStatusEnum(StrEnum):
    """Moderation state of a VoiceAgent's fixed SMS-tool text (VOAD-62).

    Not to be confused with ``MessageStatusEnum`` above, which tracks a sent
    message's delivery — this tracks whether the *configured text itself* is
    cleared to be sent at all. Text written or edited by staff starts
    ``pending`` and cannot be sent (the tool isn't even offered to the model)
    until an owner/admin/super_admin approves it; text written by
    owner/admin/super_admin is ``approved`` immediately.
    """

    approved = "approved"
    pending = "pending"
