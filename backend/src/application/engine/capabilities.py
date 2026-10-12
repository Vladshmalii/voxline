"""What a backend does, as data the engine can read.

Two speech services can implement the same methods and still behave nothing
alike. Measured against live deployments of the two recognisers this project
already speaks to:

===========================  =============================  ======================
                             Qwen3-ASR                      Voxtral
===========================  =============================  ======================
delta payload                ``language Russian<asr_text>`` the transcript alone
end of utterance             a trailing newline             no terminator at all
timing                       streams during speech          only after the commit
minimum buffer               5s, or commit returns nothing  5s, same
trailing silence             none needed                    1.5s, or the last
                                                            words are missing
detected language            reported per utterance         never reported
===========================  =============================  ======================

None of that fits in a method signature, so it lives here instead: each adapter
declares its defaults, an organization's model row may override them, and the
engine reads the result. The alternative — assumptions buried in a client — is
what makes swapping a provider return empty transcripts with no error.

Overrides come from :attr:`~src.application.engine.config.ModelConfig.capabilities`
and are applied by :meth:`Capabilities.merged`, so an operator can correct a
deployment that disagrees with its own documentation without a release.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Self

from loguru import logger


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Base for the per-kind capability sets below."""

    def merged(self, overrides: dict[str, Any]) -> Self:
        """Apply an organization's overrides on top of the adapter's defaults.

        Unknown keys are logged and ignored rather than raising: a typo in one
        organization's row should not take its calls down, and the log line is
        what tells an operator the flag never applied.

        Args:
            overrides: Keys from the model row's ``capabilities``.

        Returns:
            A new capability set.
        """
        if not overrides:
            return self
        known = {f.name for f in fields(self)}
        unknown = set(overrides) - known
        if unknown:
            logger.warning(
                f"{type(self).__name__}: ignoring unknown capability overrides {sorted(unknown)}; "
                f"known keys are {sorted(known)}"
            )
        return replace(self, **{k: v for k, v in overrides.items() if k in known})


@dataclass(frozen=True, slots=True)
class SttCapabilities(Capabilities):
    """How a recogniser behaves on the wire."""

    #: Emits partial transcripts while the caller is still speaking. When false,
    #: nothing arrives until the buffer is committed, so speculative work
    #: downstream (stable-prefix tracking, prefill) has nothing to feed on.
    streams_during_speech: bool = True
    #: Sends an explicit end-of-utterance event. When false the client has to
    #: infer one — a newline, or silence on the wire.
    emits_completion_event: bool = False
    #: Audio the server needs buffered before a commit returns anything.
    #: Measured, not guessed: below this a short reply comes back empty.
    min_commit_seconds: float = 5.0
    #: Silence appended after the speech at commit. Backends that decode until
    #: the audio stops need it, or a commit landing on the last word loses it.
    tail_silence_seconds: float = 0.0
    #: Quiet on the wire that ends an utterance, for backends with no terminator.
    finalize_after_ms: int = 800
    #: Reports the language it detected. When true it is worth comparing against
    #: the call's language and warning on disagreement; when false the frames
    #: simply carry the language the call was routed with.
    reports_language: bool = False
    #: Server-side endpointing. Left off here — Silero and the turn controller
    #: own turn boundaries, and two endpointers is a bug, not redundancy.
    server_turn_detection: bool = False
    #: Rate the client must send. Everything upstream resamples to this.
    sample_rate: int = 16000
    #: Accepts a language hint. Several deployments accept the field and ignore
    #: it, which is worse than refusing it; verify before setting this true.
    accepts_language_hint: bool = False


@dataclass(frozen=True, slots=True)
class TtsCapabilities(Capabilities):
    """How a synthesiser behaves."""

    #: Starts returning audio before the whole input is synthesised. When false,
    #: time to first byte tracks input length and chunking is the only way to
    #: keep first audio early.
    streams_incrementally: bool = False
    #: Same input, same output. When false — the common case for autoregressive
    #: codec models — speaking rate and level are redrawn per request, and the
    #: only remedy is fewer requests per turn.
    deterministic: bool = False
    #: Honours a sampling seed. Several endpoints accept one and ignore it.
    accepts_seed: bool = False
    #: Rate of the PCM it returns.
    sample_rate: int = 24000
    #: Longest input accepted in one request, if the server caps it.
    max_input_chars: int | None = None


@dataclass(frozen=True, slots=True)
class TttCapabilities(Capabilities):
    """How a language model behaves."""

    #: Accepts a tools array. Set False on endpoints without function calling
    #: to disable the built-in end_call tool.
    supports_tools: bool = True
    #: Rewards a stable prompt prefix, which is why prompt layers are ordered
    #: cacheable-first and history last.
    prefix_cache: bool = True
    #: Has a reasoning mode worth switching off for a phone call.
    reasoning_toggle: bool = True
    #: Streams token deltas. Without this the LLM/TTS overlap disappears.
    streams: bool = True
