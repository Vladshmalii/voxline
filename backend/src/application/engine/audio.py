"""Every sample-rate and encoding conversion in the audio path, in one place.

Three rates are in play and they are all different:

* **8 kHz μ-law** — the telephony leg the agent eventually runs on.
* **16 kHz PCM16** — what Qwen3-ASR consumes, and what Smart Turn v3's
  Whisper-derived feature extractor expects.
* **whatever the TTS returns** — Pipecat's output transport resamples that for
  us, so it is not handled here.

Keeping the conversions together matters because resampler objects are
*stateful*: `soxr`'s streaming resampler carries filter history between calls, so
one instance must serve exactly one stream in one direction at one rate pair.
Sharing an instance across directions produces intermittent clicks that are
maddening to trace back to their cause. :class:`AudioPath` owns one resampler per
conversion and hands out no references.
"""

from __future__ import annotations

from pipecat.audio.resamplers.base_audio_resampler import BaseAudioResampler
from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm

#: What Qwen3-ASR and Voxtral both consume. Everything upstream resamples
#: to this in one place, here.
ASR_SAMPLE_RATE = 16000
#: The telephony leg: 8 kHz µ-law, converted at the edge and nowhere else.
TELEPHONY_SAMPLE_RATE = 8000

__all__ = [
    "ASR_SAMPLE_RATE",
    "TELEPHONY_SAMPLE_RATE",
    "AudioPath",
    "bytes_for_duration",
    "duration_of",
    "seconds_for_bytes",
]

# 16-bit mono PCM: two bytes per sample, one channel.
BYTES_PER_SAMPLE = 2
CHANNELS = 1


def seconds_for_bytes(num_bytes: int, sample_rate: int) -> float:
    """Duration in seconds represented by `num_bytes` of 16-bit mono PCM."""
    if sample_rate <= 0:
        return 0.0
    return num_bytes / (sample_rate * BYTES_PER_SAMPLE * CHANNELS)


def duration_of(pcm: bytes | bytearray, sample_rate: int) -> float:
    """Duration in seconds of a 16-bit mono PCM buffer."""
    return seconds_for_bytes(len(pcm), sample_rate)


def bytes_for_duration(seconds: float, sample_rate: int) -> int:
    """Bytes of 16-bit mono PCM that hold `seconds` of audio, rounded to a sample."""
    samples = int(max(0.0, seconds) * sample_rate)
    return samples * BYTES_PER_SAMPLE * CHANNELS


class AudioPath:
    """Owns the resamplers for one call and performs every conversion.

    One instance per call. Not safe to share between calls: the resamplers carry
    per-stream filter state.
    """

    def __init__(self, *, asr_sample_rate: int = ASR_SAMPLE_RATE) -> None:
        """Initialise the per-call converters.

        Args:
            asr_sample_rate: Rate the STT backend consumes. Qwen3-ASR wants 16 kHz.
        """
        self._asr_sample_rate = asr_sample_rate
        # One resampler per conversion. See the module docstring for why these
        # are never shared.
        self._to_asr: BaseAudioResampler = create_stream_resampler()
        self._telephony_in: BaseAudioResampler = create_stream_resampler()
        self._telephony_out: BaseAudioResampler = create_stream_resampler()

    @property
    def asr_sample_rate(self) -> int:
        """Rate that :meth:`to_asr` emits."""
        return self._asr_sample_rate

    async def to_asr(self, pcm: bytes, in_rate: int) -> bytes:
        """Resample transport PCM16 to the STT backend's rate.

        A no-op when the transport already runs at the STT rate, which is the
        common case on the WebRTC dev transport. On the 8 kHz telephony leg this
        is a genuine 8 kHz → 16 kHz upsample.

        Args:
            pcm: 16-bit mono PCM from the transport.
            in_rate: Sample rate of `pcm`.

        Returns:
            16-bit mono PCM at :attr:`asr_sample_rate`.
        """
        if in_rate == self._asr_sample_rate:
            return pcm
        return await self._to_asr.resample(pcm, in_rate, self._asr_sample_rate)

    async def telephony_to_pcm(self, ulaw: bytes, out_rate: int) -> bytes:
        """Decode 8 kHz μ-law from the telephony leg to PCM16 at `out_rate`.

        Unused by the WebRTC dev transport — it exists so the SIP swap-in has one
        obvious place to call, rather than growing its own conversion.
        """
        return await ulaw_to_pcm(
            ulaw, TELEPHONY_SAMPLE_RATE, out_rate, self._telephony_in
        )

    async def pcm_to_telephony(self, pcm: bytes, in_rate: int) -> bytes:
        """Encode PCM16 at `in_rate` to 8 kHz μ-law for the telephony leg."""
        return await pcm_to_ulaw(
            pcm, in_rate, TELEPHONY_SAMPLE_RATE, self._telephony_out
        )
