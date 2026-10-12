"""Provider status webhook -> attempt result, as one pure function.

The status webhook speaks three dialects: jambonz posts JSON
(``call_status``, ``sip_status``, ``sip_reason``), Twilio posts a form
(``CallStatus``, ``SipResponseCode``, ``ErrorCode``/``ErrorMessage``), and the
SIP bridge follows whichever shape its operator mimics. :func:`extract` reads
the fields out of any of them; :func:`classify` decides what the attempt
earned. Nothing here touches the database or the network.

The SIP code, when the provider reports one, is more precise than the coarse
status word (jambonz says ``failed`` for a 404 and for a 503 alike), so it is
consulted first and the status word is the fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.common.enums.engine import CallStatusEnum

#: Non-final statuses: the call is still moving, so nothing is recorded.
PROVISIONAL_STATUSES = frozenset(
    {
        "",
        "queued",
        "initiated",
        "trying",
        "ringing",
        "early-media",
        "early_media",
        "in-progress",
        "in_progress",
        "answered",
    }
)

_STATUS_WORDS: dict[str, CallStatusEnum] = {
    "completed": CallStatusEnum.completed,
    "busy": CallStatusEnum.busy,
    "no-answer": CallStatusEnum.no_answer,
    "no_answer": CallStatusEnum.no_answer,
    "canceled": CallStatusEnum.canceled,
    "cancelled": CallStatusEnum.canceled,
}

_NO_ANSWER_CODES = frozenset({408, 480})
_BUSY_CODES = frozenset({486, 600})
_REJECTED_CODES = frozenset({603})
_INVALID_NUMBER_CODES = frozenset({404, 410, 484, 604})
#: Auth / routing / balance / limits: the platform or trunk is at fault.
_FAILURE_CODES = {
    401: "unauthorized by the trunk",
    402: "payment required (trunk balance)",
    403: "forbidden (trunk or destination not allowed)",
    407: "proxy authentication required",
    413: "request too large",
    429: "too many requests (trunk limit)",
    488: "not acceptable here (codec mismatch)",
}


@dataclass(frozen=True)
class Disposition:
    """What a final provider status means for the attempt."""

    status: CallStatusEnum
    #: Human text for ``CallAttempt.error``; set for ``failed`` only.
    error: str | None = None
    #: The status word was not recognised (the caller should warn).
    unknown: bool = False


@dataclass(frozen=True)
class ProviderPayload:
    """The disposition-relevant fields of a status webhook body."""

    status: str  # lower-cased, "" when absent
    sip_code: int | None
    reason: str | None

    @property
    def reason_text(self) -> str | None:
        """``"486 Busy Here"``-style text for ``CallAttempt.provider_reason``."""
        parts = [str(self.sip_code)] if self.sip_code is not None else []
        if self.reason:
            parts.append(self.reason)
        return " ".join(parts) or None


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def extract(payload: Mapping[str, Any]) -> ProviderPayload:
    """Read status, SIP code and reason out of a jambonz/Twilio/bridge body."""
    status = str(_first(payload, "call_status", "CallStatus") or "").strip().lower()
    raw_code = _first(payload, "sip_status", "SipResponseCode", "sip_code")
    try:
        sip_code = int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        sip_code = None
    reason = _first(payload, "sip_reason", "reason", "ErrorMessage")
    return ProviderPayload(
        status=status,
        sip_code=sip_code,
        reason=str(reason)[:500] if reason is not None else None,
    )


def _failure_text(parsed: ProviderPayload, fallback: str) -> str:
    detail = parsed.reason_text
    base = f"provider reported {parsed.status or 'failure'}"
    text = f"{base}: {detail}" if detail else f"{base} ({fallback})"
    return text[:2000]


def classify(parsed: ProviderPayload) -> Disposition | None:
    """Decide the attempt's result, or None for a provisional status."""
    status, code = parsed.status, parsed.sip_code

    if status in PROVISIONAL_STATUSES:
        return None
    if status == "completed":
        return Disposition(CallStatusEnum.completed)

    # The SIP code outranks the coarse word when it is decisive.
    if code is not None:
        if code in _NO_ANSWER_CODES:
            return Disposition(CallStatusEnum.no_answer)
        if code in _BUSY_CODES:
            return Disposition(CallStatusEnum.busy)
        if code in _REJECTED_CODES:
            return Disposition(CallStatusEnum.rejected)
        if code in _INVALID_NUMBER_CODES:
            return Disposition(CallStatusEnum.invalid_number)
        if code in _FAILURE_CODES:
            return Disposition(
                CallStatusEnum.failed,
                error=_failure_text(parsed, _FAILURE_CODES[code]),
            )
        if code >= 500:
            return Disposition(
                CallStatusEnum.failed,
                error=_failure_text(parsed, "server error / no route"),
            )

    word = _STATUS_WORDS.get(status)
    if word is not None:
        return Disposition(word)
    if status == "failed":
        return Disposition(
            CallStatusEnum.failed,
            error=_failure_text(parsed, "no SIP code, no route or provider error"),
        )
    return Disposition(
        CallStatusEnum.failed,
        error=f"unknown provider status: {status}"[:2000],
        unknown=True,
    )
