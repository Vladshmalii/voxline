"""Can this organization take a call right now?

The same question ``organization_readiness`` answers in the QA service, asked of
the voice stack: is an agent configured, are its three model servers reachable,
does the language it will use have a voice and a prompt.

Worth having as its own entry point because the failure it catches is silent.
A wrong endpoint or an expired key does not surface as an error at configuration
time — it surfaces as a customer listening to nothing, thirty seconds into a
call, with "connection refused" in a log nobody is reading yet.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import websockets
from cartesia import AsyncCartesia
from loguru import logger

# From config, not language_switch: the switcher module imports the pipeline
# stack (pipecat), and readiness must stay importable from the HTTP process.
from src.application.engine.config import (
    CallContext,
    ResolvedProfile,
    SttConfig,
    TtsConfig,
    VoiceAgentConfig,
    hot_switch_blockers,
    resolve_profile,
)
from src.common.enums.engine import SttAdapterEnum, TtsAdapterEnum
from src.utils.openrouter import api_root as openrouter_root
from src.utils.openrouter import headers as openrouter_headers
from src.utils.url import http_url

#: Per-probe timeout. Generous enough for a cold GPU box, short enough that a
#: readiness endpoint answers before its own caller times out.
PROBE_TIMEOUT_SECONDS = 5.0

#: Cartesia's REST API, when a provider row leaves the URL empty.
CARTESIA_API_URL = "https://api.cartesia.ai"

#: Deepgram's REST API, likewise.
DEEPGRAM_API_URL = "https://api.deepgram.com"

#: What a probe answers with: the endpoint to name in the report, and the
#: coroutine that decides whether it is up.
Target = tuple[str, Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Check:
    """One thing that has to be true before a call can be placed."""

    key: str
    ok: bool
    detail: str = ""


async def _probe_websocket(url: str, api_key: str | None, timeout: float) -> None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    async with asyncio.timeout(timeout):
        async with websockets.connect(url, additional_headers=headers) as ws:
            await ws.close()


async def _probe_openai(base_url: str, api_key: str | None, timeout: float) -> None:
    # /v1/models is the one endpoint every OpenAI-compatible server implements
    # and that costs nothing to call.
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()


async def _probe_cartesia(base_url: str, api_key: str | None, timeout: float) -> None:
    # Listing one voice is the cheapest call that exercises everything a
    # misconfigured row breaks: the host, the key, and the API version the SDK
    # pins. The websocket routes themselves cannot be probed without opening a
    # transcription or synthesis session, which costs money and proves no more.
    client = AsyncCartesia(api_key=api_key or "", base_url=base_url)
    try:
        async with asyncio.timeout(timeout):
            await client.voices.list(limit=1)
    finally:
        await client.close()


async def _probe_deepgram(base_url: str, api_key: str | None, timeout: float) -> None:
    # Deepgram's model list is the /models of this API: it needs a valid key,
    # costs nothing, and fails the same way a real connection would when the
    # host or the key is wrong. Plain HTTP rather than the vendor SDK, because
    # pointing that client at a custom host means building its environment
    # object, and this probe only has to reach the host the row names.
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Token {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()


async def _probe_openrouter(base_url: str, api_key: str | None, timeout: float) -> None:
    # ``/key`` describes the key the request was made with: it needs a valid one,
    # costs nothing, and is the only cheap call here that actually fails on an
    # expired key. ``/models`` would not — it is public, so it answers 200 with
    # no credentials at all and would pass a row whose key was revoked months ago.
    url = f"{base_url.rstrip('/')}/key"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=openrouter_headers(api_key))
        response.raise_for_status()


def _websocket_target(config: SttConfig, timeout: float) -> Target:
    """The default recogniser probe: dial the URI a call would dial."""
    url = config.websocket_url()
    return url, _probe_websocket(url, config.model.provider.api_key, timeout)


def _openai_target(config: TtsConfig, timeout: float) -> Target:
    """The default synthesiser probe: an OpenAI-compatible model list."""
    url = config.model.provider.url
    return url, _probe_openai(url, config.model.provider.api_key, timeout)


def _cartesia_target(config: SttConfig | TtsConfig, timeout: float) -> Target:
    """Cartesia's REST API, whichever kind of model the row binds."""
    url = (
        http_url(config.model.provider.url)
        if config.model.provider.url
        else CARTESIA_API_URL
    )
    return url, _probe_cartesia(url, config.model.provider.api_key, timeout)


def _deepgram_target(config: SttConfig | TtsConfig, timeout: float) -> Target:
    """Deepgram's REST API, whichever kind of model the row binds."""
    url = (
        http_url(config.model.provider.url)
        if config.model.provider.url
        else DEEPGRAM_API_URL
    )
    return url, _probe_deepgram(url, config.model.provider.api_key, timeout)


def _openrouter_target(config: SttConfig | TtsConfig, timeout: float) -> Target:
    """OpenRouter's API root, whichever kind of model the row binds.

    One entry for both kinds because it is one account and one host: an
    organization's recogniser and synthesiser rows point at the same place and
    differ only in the slug.
    """
    url = openrouter_root(
        http_url(config.model.provider.url) if config.model.provider.url else ""
    )
    return url, _probe_openrouter(url, config.model.provider.api_key, timeout)


#: Probes for backends whose servers are not the shape the defaults assume.
#: A registry rather than a branch, for the same reason the adapters are one:
#: a vendor that authenticates differently or has no model-list endpoint is a
#: row here, not an ``if`` inside the probe.
STT_PROBES: dict[SttAdapterEnum, Callable[[SttConfig, float], Target]] = {
    SttAdapterEnum.cartesia: _cartesia_target,
    SttAdapterEnum.deepgram: _deepgram_target,
    SttAdapterEnum.openrouter: _openrouter_target,
}
TTS_PROBES: dict[TtsAdapterEnum, Callable[[TtsConfig, float], Target]] = {
    TtsAdapterEnum.cartesia: _cartesia_target,
    TtsAdapterEnum.deepgram: _deepgram_target,
    TtsAdapterEnum.openrouter: _openrouter_target,
}


async def probe_profile(
    profile: ResolvedProfile, *, timeout: float = PROBE_TIMEOUT_SECONDS
) -> list[Check]:
    """Probe every model server a call with this profile would use.

    All three are probed even after the first failure: being told about the
    recogniser, fixing it, and only then learning the synthesiser is also down
    wastes a cycle per broken service.

    Args:
        profile: The settings a call would run with.
        timeout: Per-probe timeout in seconds.

    Returns:
        One check per server, naming the endpoint that failed.
    """
    # The same derivation the adapters' from_config runs, so the probe reaches
    # exactly the endpoint a call would — an https:// provider row bound to a
    # realtime recogniser is probed as the wss:// URI it resolves to, and a
    # vendor with its own API shape is probed through its own entry above.
    stt_url, stt_probe = STT_PROBES.get(profile.stt.adapter, _websocket_target)(
        profile.stt, timeout
    )
    tts_url, tts_probe = TTS_PROBES.get(profile.tts.adapter, _openai_target)(
        profile.tts, timeout
    )
    targets: list[tuple[str, str, Any]] = [
        (f"stt:{profile.stt.adapter}", stt_url, stt_probe),
        (
            f"ttt:{profile.ttt.adapter}",
            profile.ttt.model.provider.url,
            _probe_openai(
                profile.ttt.model.provider.url,
                profile.ttt.model.provider.api_key,
                timeout,
            ),
        ),
        (f"tts:{profile.tts.adapter}", tts_url, tts_probe),
    ]

    results = await asyncio.gather(*(t[2] for t in targets), return_exceptions=True)
    checks: list[Check] = []
    for (key, url, _), result in zip(targets, results):
        failed = isinstance(result, BaseException)
        if failed:
            logger.warning(
                f"readiness: {key} at {url} — {type(result).__name__}: {result}"
            )
        checks.append(
            Check(
                key=key,
                ok=not failed,
                detail=url
                if not failed
                else f"{url} — {type(result).__name__}: {result}",
            )
        )
    return checks


def check_profile(profile: ResolvedProfile) -> list[Check]:
    """Check a profile for the mistakes that need no network to find.

    Args:
        profile: The settings a call would run with.

    Returns:
        One check per rule, all of them cheap.
    """
    voice = profile.tts.voice
    return [
        Check(
            "prompt",
            bool(profile.prompts.system_prompt.strip()),
            "system prompt is set",
        ),
        Check(
            "greeting",
            not profile.greet_first or bool(profile.prompts.greeting_kickoff.strip()),
            "an agent that speaks first needs a greeting kickoff",
        ),
        Check("voice", bool(voice) and voice != "REPLACE_ME", f"voice={voice!r}"),
        Check(
            "spoken_prompts",
            all(
                (
                    profile.spoken.silence,
                    profile.spoken.reprompt,
                    profile.spoken.goodbye,
                )
            ),
            "silence, reprompt and goodbye lines are set",
        ),
        Check(
            "turn",
            profile.turn.min_delay_ms < profile.turn.max_delay_ms,
            f"min={profile.turn.min_delay_ms}ms < max={profile.turn.max_delay_ms}ms",
        ),
    ]


def check_language_switch(agent: VoiceAgentConfig) -> list[Check]:
    """Which configured languages a live call could actually switch to.

    Only meaningful when the agent's switch policy is on — with it off the
    answer is "none, by choice" and no checks are emitted. A language row that
    routes to a different recogniser, LLM, or anything else built once per
    call will be *refused* at switch time; an organization that enabled
    switching expecting it to work should hear that here, not from a caller.

    Offline and cheap: the same :func:`hot_switch_blockers` the switcher asks
    live, asked of every language row against the agent's defaults.

    Args:
        agent: The organization's agent configuration.

    Returns:
        One check per configured language, naming the blockers when not ok.
    """
    if not agent.language_switch.enabled:
        return []
    probe_call = CallContext(call_id="readiness", org_uuid="readiness")
    base = resolve_profile(agent, probe_call)
    checks: list[Check] = []
    for key in sorted(agent.languages):
        target = resolve_profile(agent, probe_call.model_copy(update={"language": key}))
        blockers = hot_switch_blockers(base, target)
        checks.append(
            Check(
                key=f"language_switch:{key}",
                ok=not blockers,
                detail="hot-switchable" if not blockers else "; ".join(blockers),
            )
        )
    return checks


async def readiness(
    profile: ResolvedProfile,
    *,
    agent: VoiceAgentConfig | None = None,
    probe: bool = True,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Full readiness for one organization's resolved profile.

    Args:
        profile: The settings a call would run with.
        agent: Optionally the full agent, to also verify that every language
            row is reachable by a mid-call switch when the policy enables one.
        probe: Whether to reach out to the model servers. False keeps it local,
            for a health endpoint that must stay fast.
        timeout: Per-probe timeout in seconds.

    Returns:
        ``{"ready": bool, "checks": [{"key", "ok", "detail"}, ...]}``, shaped to
        match the readiness payloads the other services already return.
    """
    checks = check_profile(profile)
    if agent is not None:
        checks += check_language_switch(agent)
    if probe:
        checks += await probe_profile(profile, timeout=timeout)
    return {
        "ready": all(c.ok for c in checks),
        "checks": [{"key": c.key, "ok": c.ok, "detail": c.detail} for c in checks],
    }
