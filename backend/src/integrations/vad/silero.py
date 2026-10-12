"""Silero VAD, and Smart Turn v3 as the end-of-turn analyzer.

Both run in-process on CPU. Hooks workers preload the shared ONNX sessions
at startup; other entry points load them on demand. Each call owns its
analyzer, audio buffers and recurrent state. Silero decides
when the expensive recogniser is allowed to run, and Smart Turn is consulted
on demand, with the buffered segment, by the turn controller.
"""

from __future__ import annotations

import math
from importlib.resources import files

from pipecat.audio.turn.smart_turn.base_smart_turn import BaseSmartTurn, SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroOnnxModel, SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams
from pipecat.audio.volume import VOLUME_WINDOW_SECS
from pipecat.utils.env import env_truthy

from src.application.engine.config import TurnParams, VadConfig
from src.common.enums.engine import TurnAnalyzerEnum, VadAdapterEnum
from src.integrations.vad.base import TurnAnalyzers, VadAdapters
from src.integrations.vad.onnx_sessions import cpu_session

SILERO_MODEL_PATH = str(files("pipecat.audio.vad.data").joinpath("silero_vad.onnx"))
SMART_TURN_MODEL_PATH = str(
    files("pipecat.audio.turn.smart_turn.data").joinpath("smart-turn-v3.2-cpu.onnx")
)

#: Headroom between the analyzer's own timer and the controller's ceiling.
#: ``BaseSmartTurn`` ends a turn by itself once it has seen ``stop_secs`` of
#: silence, which would race ``max_delay_ms`` and take the decision — including
#: the fragment classification that only happens on a ceiling commit — out of
#: the controller's hands. Sitting comfortably above the ceiling leaves the
#: controller the sole authority on when a turn ends.
SMART_TURN_HEADROOM_SECONDS = 2.0


def warmup_models() -> None:
    """Load bundled weights into this process's cache before accepting calls.

    Use the same paths and CPU settings as the call factories. No analyzers,
    audio state, executors or provider connections are created here. Load
    errors propagate so hooks startup cannot report readiness after a failure.
    """
    cpu_session(SILERO_MODEL_PATH)
    cpu_session(SMART_TURN_MODEL_PATH)


class _CallSileroModel(SileroOnnxModel):
    """Pipecat's recurrent inference with call-local state and shared weights."""

    def __init__(self):
        # Pipecat has no session injection hook. Bypass only its model
        # loading constructor, retaining upstream inference and reset logic.
        self.session = cpu_session(SILERO_MODEL_PATH)
        self.reset_states()
        self.sample_rates = [8000, 16000]


class SileroVAD(SileroVADAnalyzer):
    """Frame-by-frame speech detection."""

    def __init__(
        self, *, sample_rate: int | None = None, params: VADParams | None = None
    ):
        # Initialize all per-call VAD state without loading a second session.
        VADAnalyzer.__init__(self, sample_rate=sample_rate, params=params)
        self._model = _CallSileroModel()
        self._last_reset_time = 0

    def set_sample_rate(self, sample_rate: int):
        """Adopt the call's rate, ready to hear speech from its first frame.

        Pipecat 1.8 measures volume over a rolling 400 ms window that reads 0
        until full, and ``min_volume`` gates speech on it — so a caller who
        answers with a short "Алло?" in the leg's first ~0.4 s was not heard
        at all (1.7.0 measured each chunk on its own). Starting the window
        full of silence restores hearing from the first frame; the window
        only ever empties again if the sample rate changes.
        """
        super().set_sample_rate(sample_rate)
        self._volume_tracker.update(
            bytes(math.ceil(VOLUME_WINDOW_SECS * self.sample_rate) * 2),
            self.sample_rate,
        )

    @classmethod
    def from_config(cls, config: VadConfig, sample_rate: int) -> SileroVAD:
        """Build a detector from an organization's VAD settings.

        Args:
            config: Resolved VAD settings.
            sample_rate: Rate of the audio it will see.

        Returns:
            A ready analyzer.
        """
        return cls(
            sample_rate=sample_rate,
            params=VADParams(
                confidence=config.confidence,
                start_secs=config.start_secs,
                stop_secs=config.stop_secs,
                min_volume=config.min_volume,
            ),
        )


class SmartTurnV3(LocalSmartTurnAnalyzerV3):
    """Whether the caller has finished, rather than merely paused."""

    def __init__(
        self,
        *,
        smart_turn_model_path: str | None = None,
        cpu_count: int = 1,
        sample_rate: int | None = None,
        params: SmartTurnParams | None = None,
    ):
        # Pipecat initializes the buffer (and its lazy executor) in
        # BaseSmartTurn, but unconditionally loads ONNX in
        # LocalSmartTurnAnalyzerV3.__init__. Keep its prediction
        # implementation and replace only session loading.
        BaseSmartTurn.__init__(self, sample_rate=sample_rate, params=params)
        self._log_data = env_truthy("PIPECAT_SMART_TURN_LOG_DATA", default=False)
        model_path = smart_turn_model_path or SMART_TURN_MODEL_PATH
        self._session = cpu_session(model_path, cpu_count=cpu_count)

    @classmethod
    def from_config(cls, params: TurnParams, sample_rate: int) -> SmartTurnV3:
        """Build the analyzer from an organization's turn settings.

        Args:
            params: Resolved turn settings. Its ``max_delay_ms`` sets the
                analyzer's own timer high enough to stay out of the way.
            sample_rate: Rate of the audio it will see.

        Returns:
            A ready analyzer.
        """
        return cls(
            sample_rate=sample_rate,
            params=SmartTurnParams(
                stop_secs=params.max_delay_ms / 1000 + SMART_TURN_HEADROOM_SECONDS
            ),
        )


VadAdapters[VadAdapterEnum.silero] = SileroVAD
TurnAnalyzers[TurnAnalyzerEnum.smart_turn_v3] = SmartTurnV3
