"""Voice activity detection and end-of-turn analysis, and their registries.

Two separate decisions, kept apart because they answer different questions and
are configured independently:

* **VAD** — is there speech in this frame? Runs on every frame, in-process,
  cheap. It opens the recogniser's gate and starts the turn controller's clock.
* **Turn analyzer** — has the caller *finished*? Consulted on demand with the
  buffered segment, expensive, and wrong often enough for some languages that
  it can be switched off per language in favour of a tuned silence threshold.

Treating a VAD stop as the end of a turn is the classic voice-agent bug: the
agent interrupts every time the caller draws breath.
"""

from __future__ import annotations

from pipecat.audio.turn.base_turn_analyzer import BaseTurnAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer

from src.application.engine.config import TurnParams, VadConfig
from src.common.enums.engine import TurnAnalyzerEnum, VadAdapterEnum

#: name -> factory taking the resolved VAD settings.
VadAdapters: dict[VadAdapterEnum, type] = {}

#: name -> factory taking the resolved turn settings and the sample rate.
TurnAnalyzers: dict[TurnAnalyzerEnum, type] = {}


def build_vad(config: VadConfig, sample_rate: int) -> VADAnalyzer:
    """Resolve and build the detector named by `config`.

    Args:
        config: Resolved VAD settings.
        sample_rate: Rate of the audio it will see.

    Returns:
        An analyzer ready to be handed to the transport and the aggregator.

    Raises:
        KeyError: if no adapter is registered under that name.
    """
    adapter = VadAdapters.get(config.adapter)
    if adapter is None:
        raise KeyError(
            f"no VAD adapter registered as {config.adapter!r}. Registered: {sorted(VadAdapters)}"
        )
    return adapter.from_config(config, sample_rate)


def build_turn_analyzer(
    params: TurnParams, sample_rate: int
) -> BaseTurnAnalyzer | None:
    """Resolve and build the end-of-turn analyzer named by `params`.

    Args:
        params: Resolved turn settings.
        sample_rate: Rate of the audio it will see.

    Returns:
        An analyzer, or None when this language runs on the silence threshold
        alone — which is the honest setting for a language the analyzer was
        never trained on.

    Raises:
        KeyError: if no analyzer is registered under that name.
    """
    if params.analyzer == TurnAnalyzerEnum.none or not params.smart_turn:
        return None
    adapter = TurnAnalyzers.get(params.analyzer)
    if adapter is None:
        raise KeyError(
            f"no turn analyzer registered as {params.analyzer!r}. "
            f"Registered: {sorted(TurnAnalyzers)}"
        )
    return adapter.from_config(params, sample_rate)
