"""truth_lens/prosody.py — Voice stress / prosody analysis."""
from __future__ import annotations
import math
from typing import Optional
import numpy as np
from .schema import ProsodyFrame

SAMPLE_RATE_HZ = 16_000
FFT_SIZE = 512
BIN_HZ = SAMPLE_RATE_HZ / FFT_SIZE
F0_MIN_BIN = int(80 / BIN_HZ)
F0_MAX_BIN = int(400 / BIN_HZ)
SILENCE_THRESHOLD = 0.02
FRAMES_PER_WINDOW = 40


def _estimate_f0(fft: Optional[np.ndarray]) -> Optional[float]:
    if fft is None or len(fft) < F0_MAX_BIN:
        return None
    region = fft[F0_MIN_BIN:F0_MAX_BIN]
    if region.max() < 1e-4:
        return None
    return (int(np.argmax(region)) + F0_MIN_BIN) * BIN_HZ


def _to_db(amp: float) -> float:
    return max(20.0 * math.log10(amp), -60.0) if amp > 0 else -60.0


class ProsodyAnalyzer:
    def __init__(self, frames_per_window: int = FRAMES_PER_WINDOW):
        self.frames_per_window = frames_per_window
        self._ffts: list = []
        self._amps: list = []
        self._baseline_density: float = 0.75

    def feed(self, mic_fft: Optional[np.ndarray],
             amplitude: Optional[float]) -> Optional[ProsodyFrame]:
        self._ffts.append(mic_fft)
        self._amps.append(amplitude or 0.0)
        if len(self._ffts) >= self.frames_per_window:
            frame = self._analyse(self._ffts[:self.frames_per_window],
                                  self._amps[:self.frames_per_window])
            self._ffts = self._ffts[self.frames_per_window:]
            self._amps = self._amps[self.frames_per_window:]
            return frame
        return None

    def _analyse(self, ffts: list, amps: list) -> ProsodyFrame:
        f0s = [f0 for fft in ffts if (f0 := _estimate_f0(fft)) is not None]
        pitch_mean = sum(f0s) / len(f0s) if f0s else 0.0
        pitch_var = float(np.var(f0s)) if len(f0s) > 1 else 0.0
        jitter = 0.0
        if len(f0s) >= 2:
            diffs = [abs(f0s[i] - f0s[i-1]) for i in range(1, len(f0s))]
            jitter = (sum(diffs) / len(diffs)) / max(pitch_mean, 1.0) * 100
        shimmer = 0.0
        voiced_amps = [a for a in amps if a >= SILENCE_THRESHOLD]
        if len(voiced_amps) >= 2:
            diffs = [abs(voiced_amps[i] - voiced_amps[i-1])
                     for i in range(1, len(voiced_amps))]
            mean_amp = sum(voiced_amps) / len(voiced_amps)
            shimmer = (sum(diffs) / len(diffs)) / max(mean_amp, 1e-6) * 100
        silent = sum(1 for a in amps if a < SILENCE_THRESHOLD)
        pause_ratio = silent / len(amps)
        hesitations = sum(
            1 for i in range(1, len(amps))
            if amps[i-1] >= SILENCE_THRESHOLD
            and amps[i] < SILENCE_THRESHOLD
            and (i + 1 < len(amps) and amps[i+1] >= SILENCE_THRESHOLD)
        )
        window_sec = len(amps) / max(SAMPLE_RATE_HZ / FFT_SIZE, 1)
        hesitation_rate = hesitations / max(window_sec, 0.001)
        voiced_density = 1.0 - pause_ratio
        speech_rate = voiced_density / max(self._baseline_density, 0.01)
        self._baseline_density = 0.95 * self._baseline_density + 0.05 * voiced_density
        energy_db = _to_db(sum(amps) / len(amps))
        return ProsodyFrame(
            pitch_mean_hz=round(pitch_mean, 2),
            pitch_variance=round(pitch_var, 2),
            jitter_pct=round(jitter, 3),
            shimmer_pct=round(shimmer, 3),
            hesitation_rate=round(hesitation_rate, 3),
            pause_ratio=round(pause_ratio, 3),
            speech_rate_norm=round(speech_rate, 3),
            energy_db=round(energy_db, 1),
        )
