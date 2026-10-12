"""Post-call analysis: the agent's own LLM reads the transcript and returns
a short summary, a business outcome, and — when the caller named one — the
moment to call back.

Runs in the worker after an attempt completes (``tasks.analyze_attempt``),
against the organization's analysis model (``Model.is_analysis``) or, with
none flagged, the TTT endpoint the call itself used, as one non-streaming
chat-completions request. The model is asked for bare JSON; parsing is
deliberately tolerant (fences, prose around the object) because "the analysis
crashed" must never be the reason an outcome is lost — a row the parser cannot
save is retried by the next dispatcher tick.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel

from src.common.enums.campaign import CallOutcomeEnum, ReasonCategoryEnum, SentimentEnum
from src.schemas.engine import TttConfig

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_SUMMARY_CHARS = 1000
#: A recall date further out than this is a hallucinated year, not a plan.
MAX_RECALL_HORIZON = timedelta(days=30)

#: Outcomes the model may assign. ``no_answer`` is excluded on purpose — it is
#: derived from telephony status in the settle step, never from a transcript;
#: ``sms_sent`` likewise comes from a ``Message`` row (VOAD-80).
ASSIGNABLE_OUTCOMES = frozenset(CallOutcomeEnum) - {
    CallOutcomeEnum.no_answer,
    CallOutcomeEnum.sms_sent,
}

#: First line of the customer-profile prompt layer, as rendered by
#: ``engine/context/assembly.py`` — used to keep scaffolding out of transcripts.
PROFILE_HEADER = "Customer profile for this call:"


class AnalysisError(ValueError):
    """The endpoint or its reply was unusable; the message says why."""


class AnalysisResult(BaseModel):
    summary: str
    outcome: CallOutcomeEnum
    recall_at: datetime | None = None
    #: One of the offer labels passed to :func:`build_messages`, or None —
    #: never free text the model invented, see :func:`parse_analysis`.
    selected_offer: str | None = None
    sentiment: SentimentEnum | None = None
    reason_category: ReasonCategoryEnum | None = None


def offer_label(offer: Any) -> str:
    """A short, readable label for one entry of ``Call.bonuses``.

    Bonuses are free-form JSON (per-campaign data, not a fixed schema); this
    is only ever used to show the model a pickable list and to check its
    answer against it, never persisted as the offer itself.
    """
    if isinstance(offer, dict):
        for key in ("title", "name", "id"):
            value = offer.get(key)
            if value:
                return str(value)
        return json.dumps(offer, ensure_ascii=False)
    return str(offer)


def render_transcript(
    messages: list[Any], *, scaffolding: frozenset[str] = frozenset()
) -> str:
    """The conversation as reader-facing lines, prompt scaffolding removed.

    Attempt messages are the full LLM context: system prompt, the customer
    profile layer, the greeting kickoff stage direction, then real turns.
    Only the real turns belong in an analysis transcript.

    Args:
        messages: The attempt's stored messages.
        scaffolding: Exact message bodies to drop (the greeting kickoff).

    Returns:
        ``agent:``/``caller:`` lines, empty when nothing was really said.
    """
    lines: list[str] = []
    for message in messages:
        role, content = message.get("role"), message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        text = content.strip()
        if not text or text in scaffolding or text.startswith(PROFILE_HEADER):
            continue
        lines.append(f"{'caller' if role == 'user' else 'agent'}: {text}")
    return "\n".join(lines)


def build_messages(
    transcript: str, *, language: str, now: datetime, offers: list[str] = ()
) -> list[dict[str, str]]:
    """The analysis request, as chat messages."""
    outcomes = "\n".join(
        f"- {value}" for value in sorted(v.value for v in ASSIGNABLE_OUTCOMES)
    )
    offer_field = ""
    offer_instruction = ""
    if offers:
        offer_list = "\n".join(f"- {label}" for label in offers)
        offer_field = ', "selected_offer": "..." or null'
        offer_instruction = (
            "\nselected_offer: which one of these offers the customer accepted, "
            f"copied exactly, or null if none was:\n{offer_list}\n"
        )
    sentiments = "\n".join(f"- {value.value}" for value in SentimentEnum)
    reasons = "\n".join(f"- {value.value}" for value in ReasonCategoryEnum)
    instructions = (
        "You analyze a finished phone call between a company's voice agent and a customer.\n"
        f"Current date and time: {now.isoformat(timespec='minutes')}.\n\n"
        "Reply with ONLY a JSON object, no other text:\n"
        '{"summary": "...", "outcome": "...", "recall_at": "..." or null, '
        f'"sentiment": "...", "reason_category": "..." or null{offer_field}}}\n\n'
        f"summary: 2-3 sentences, in the call's language ({language}): what was "
        "discussed and how it ended.\n"
        f"outcome: exactly one of:\n{outcomes}\n"
        "Pick answerphone when voicemail, an automated greeting, or an answering machine was reached.\n"
        "Pick escalated when the customer requested to speak with a human agent, supervisor, or requested a callback from staff.\n"
        "Pick do_not_call only when the customer asked not to be contacted again. "
        "Pick call_later when they asked to be called back another time.\n"
        'recall_at: only with outcome "call_later" and only if the customer named a '
        'specific time — as "YYYY-MM-DDTHH:MM" resolved against the current date '
        "and time above. Otherwise null.\n"
        f"sentiment: the customer's overall tone, exactly one of:\n{sentiments}\n"
        'reason_category: only with outcome "not_interested", the main reason they '
        f"declined, exactly one of:\n{reasons}\nOtherwise null."
        f"{offer_instruction}"
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": f"Transcript:\n{transcript}"},
    ]


def parse_analysis(
    text: str, *, now: datetime, offers: list[str] = ()
) -> AnalysisResult:
    """Pull the result out of whatever the model wrapped it in.

    Args:
        offers: Labels the model was offered to pick ``selected_offer`` from
            (see :func:`build_messages`). An answer outside this set — a
            hallucinated offer — is dropped rather than trusted.

    Raises:
        AnalysisError: When no valid JSON object with a known outcome is found.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise AnalysisError(f"no JSON object in reply: {text[:200]!r}")
    try:
        payload = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"unparseable JSON in reply: {exc}") from exc

    outcome_raw = str(payload.get("outcome", "")).strip().lower()
    if outcome_raw not in ASSIGNABLE_OUTCOMES:
        raise AnalysisError(f"unknown outcome {outcome_raw!r}")
    outcome = CallOutcomeEnum(outcome_raw)

    summary = str(payload.get("summary", "")).strip()[:MAX_SUMMARY_CHARS]

    recall_at: datetime | None = None
    raw_recall = payload.get("recall_at")
    if raw_recall and outcome == CallOutcomeEnum.call_later:
        try:
            recall_at = datetime.fromisoformat(str(raw_recall)).replace(tzinfo=None)
        except ValueError:
            recall_at = None  # a garbled time falls back to the retry policy
        else:
            if recall_at <= now or recall_at > now + MAX_RECALL_HORIZON:
                recall_at = None

    selected_offer: str | None = None
    raw_offer = payload.get("selected_offer")
    if raw_offer and offers:
        raw_offer = str(raw_offer).strip()
        selected_offer = next((o for o in offers if o == raw_offer), None)

    sentiment: SentimentEnum | None = None
    raw_sentiment = str(payload.get("sentiment", "")).strip().lower()
    if raw_sentiment in iter(SentimentEnum):
        sentiment = SentimentEnum(raw_sentiment)

    reason_category: ReasonCategoryEnum | None = None
    raw_reason = str(payload.get("reason_category", "")).strip().lower()
    if outcome == CallOutcomeEnum.not_interested and raw_reason in iter(
        ReasonCategoryEnum
    ):
        reason_category = ReasonCategoryEnum(raw_reason)

    return AnalysisResult(
        summary=summary,
        outcome=outcome,
        recall_at=recall_at,
        selected_offer=selected_offer,
        sentiment=sentiment,
        reason_category=reason_category,
    )


async def analyze_transcript(
    ttt: TttConfig,
    transcript: str,
    *,
    language: str,
    now: datetime | None = None,
    offers: list[str] = (),
) -> AnalysisResult:
    """One non-streaming completion against the analysis LLM endpoint.

    Args:
        ttt: The organization's analysis model, or the call's own LLM.
        transcript: Output of :func:`render_transcript`, non-empty.
        language: Language for the summary.
        now: Reference moment for resolving relative recall times.
        offers: Labels of this call's available offers (``Call.bonuses``, via
            :func:`offer_label`); empty when the call had none.

    Returns:
        The parsed analysis.

    Raises:
        AnalysisError: On transport errors, bad status, or an unusable reply.
    """
    now = now or datetime.now()
    body: dict[str, Any] = {
        "model": ttt.model.code,
        "messages": build_messages(
            transcript, language=language, now=now, offers=offers
        ),
        # Deterministic classification, not conversation; and no thinking —
        # same reasoning-off default the call path uses, same mechanism.
        # No max_tokens: a cap cut mid-object is unparseable JSON, retried
        # forever; the summary is trimmed after parsing (MAX_SUMMARY_CHARS)
        # and REQUEST_TIMEOUT_SECONDS bounds a runaway reply instead.
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Authorization": f"Bearer {ttt.model.provider.api_key or 'not-needed'}"}
    url = f"{ttt.model.provider.url.rstrip('/')}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            reply = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise AnalysisError(f"analysis request to {url} failed: {exc}") from exc
    return parse_analysis(reply, now=now, offers=offers)
