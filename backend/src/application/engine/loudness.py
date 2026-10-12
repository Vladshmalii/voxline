"""Match the loudness of consecutive TTS chunks inside one call.

Every chunk of a reply is a separate synthesis request, and Qwen3-TTS samples
each one independently. Measured against the deployed endpoint by sending the
*same* Russian sentence three times in a row:

    4.96 s  rms 3526
    5.04 s  rms 3317
    5.76 s  rms 2662

and across a wider sweep the RMS for identical input ranged from 2451 to 5025 —
just over 6 dB apart. ``seed``, ``temperature`` and ``top_p`` are accepted by the
endpoint and ignored (three requests at a fixed seed return three different
waveforms), so the variation cannot be turned off at the source.

A caller hears that as the agent changing voice mid-sentence. Level is the part
of it that is fixable from this side: the first chunk of the call sets the
reference, every later chunk is scaled to match it. Speaking rate and timbre are
sampled per request too and no amount of gain fixes those — the only real remedy
there is fewer requests per turn, which is what services/chunking.py is for.

The first chunk is never touched, so nothing is buffered on the path to first
audio; it defines the loudness the rest of the call is matched to.
"""

from __future__ import annotations

from typing import Final

import audioop  # provided by audioop-lts, a Pipecat dependency on Python 3.13+
from loguru import logger

#: PCM16, the only format this pipeline moves.
SAMPLE_WIDTH: Final[int] = 2

#: RMS below this is silence, a breath, or a truncated chunk. Such a chunk is
#: neither used as a reference nor corrected — dividing by it would produce an
#: enormous gain and amplify the room noise the model synthesised.
SILENCE_FLOOR: Final[int] = 200

#: Largest correction, as a linear factor. 2.0 is 6 dB either way, which covers
#: the measured spread; anything beyond it is not level drift but a different
#: kind of failure, and quietly rescaling it would hide that.
MAX_GAIN: Final[float] = 2.0

#: Corrections below this are inaudible (≈0.4 dB). Skipping them keeps most
#: chunks on the zero-copy path.
MIN_AUDIBLE_GAIN: Final[float] = 0.05

#: Peak to stay under after scaling, leaving a little headroom below int16 max
#: so the correction can never introduce clipping of its own.
PEAK_CEILING: Final[int] = 32000


class ChunkLoudnessMatcher:
    """Scales each TTS chunk to the loudness of the call's first chunk.

    One instance per call — the reference is what the caller first heard, so it
    must not leak across calls. The TTS service is constructed per call by
    services/router.py, which gives that for free.
    """

    def __init__(
        self, *, max_gain: float = MAX_GAIN, silence_floor: int = SILENCE_FLOOR
    ) -> None:
        """Initialise the matcher.

        Args:
            max_gain: Largest linear correction applied, in either direction.
            silence_floor: RMS under which a chunk is treated as silence.
        """
        self._max_gain = max(1.0, max_gain)
        self._silence_floor = silence_floor
        self._reference: int | None = None

    @property
    def reference(self) -> int | None:
        """RMS every later chunk is matched to, or ``None`` until one is set."""
        return self._reference

    def observe(self, pcm: bytes) -> None:
        """Take this chunk as the call's reference loudness, if it has any.

        Called for the first chunk of a call, which is passed through unchanged
        so that nothing is buffered on the path to first audio.

        Args:
            pcm: The chunk's PCM16 audio.
        """
        if self._reference is not None or not pcm:
            return
        rms = audioop.rms(pcm, SAMPLE_WIDTH)
        if rms < self._silence_floor:
            return
        self._reference = rms
        logger.debug(f"loudness: reference set to rms {rms}")

    def match(self, pcm: bytes) -> bytes:
        """Return this chunk scaled to the reference loudness.

        Args:
            pcm: The chunk's PCM16 audio.

        Returns:
            The scaled audio, or the input unchanged when there is no reference
            yet, the chunk is silence, or the correction would be inaudible.
        """
        if not pcm:
            return pcm
        if self._reference is None:
            self.observe(pcm)
            return pcm

        rms = audioop.rms(pcm, SAMPLE_WIDTH)
        if rms < self._silence_floor:
            return pcm

        gain = self._reference / rms
        gain = min(max(gain, 1 / self._max_gain), self._max_gain)

        # Never let the correction clip. audioop.mul saturates rather than
        # wrapping, so this is about fidelity, not about avoiding a bang.
        peak = audioop.max(pcm, SAMPLE_WIDTH)
        if peak > 0:
            gain = min(gain, PEAK_CEILING / peak)

        if abs(gain - 1.0) < MIN_AUDIBLE_GAIN:
            return pcm

        logger.debug(f"loudness: chunk rms {rms} → {self._reference} (gain {gain:.2f})")
        return audioop.mul(pcm, SAMPLE_WIDTH, gain)
