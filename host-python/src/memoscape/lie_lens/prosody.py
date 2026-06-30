"""lie_lens/prosody.py — Voice prosody + stress analysis.

Absorbs and extends the lie_sense module.
Extracts pitch, jitter, shimmer, hesitation rate from raw mic FFT data
already produced by the existing audio pipeline.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional

import numpy as np

from .schema import ProsodyFrame

# FFT parameters (matches existing mic pipeline)
SAMPLE_RATE_HZ = 16_000
FFT_SIZE = 512
BIN_HZ = SAMPLE_RATE_HZ / FFT_SIZE
F0_MIN_BIN = int(80 / BIN_HZ)
F0_MAX_BIN = int(400 / BIN_HZ)
SILENCE_THRESHOLD = 0.02
FRAMES_PER_WINDOW = 40   # ~250ms at ~160fps


def _estimate_f0(fft_mag: np.ndarray) -> Optional[float]:
    if fft_mag is None or len(fft_mag) < F0_MAX_BIN:
        return None
    region = fft_mag[F0_MIN_BIN:F0_MAX_BIN]
    if region.max() < 1e-4:
        return None
    return (int(np.argmax(region)) + F0_MIN_BIN) * BIN_HZ


def _amp_db(amp: float) -> float:
    return max(20.0 * math.log10(amp), -60.0) if amp > 0 else -60.0


class ProsodyAnalyzer:
    """Accumulates mic frames and emits ProsodyFrame per completed window."""

    def __init__(self, frames_per_window: int = FRAMES_PER_WINDOW,
                 max_windows: int = 20):
        self._fpw = frames_per_window
        self._max = max_windows
        self._pending_fft: list[Optional[np.ndarray]] = []
        self._pending_amp: list[float] = []
        self._windows: deque[ProsodyFrame] = deque(maxlen=max_windows)
        self._baseline_density: float = 0.75

    def feed(self, mic_fft: Optional[np.ndarray],
             mic_amplitude: Optional[float]) -> Optional[ProsodyFrame]:
        """Feed one audio frame. Returns ProsodyFrame when window completes."""
        self._pending_fft.append(mic_fft)
        self._pending_amp.append(mic_amplitude or 0.0)
        if len(self._pending_amp) < self._fpw:
            return None
        frame = self._analyse(self._pending_fft[:self._fpw],
                              self._pending_amp[:self._fpw])
        self._pending_fft = self._pending_fft[self._fpw:]
        self._pending_amp = self._pending_amp[self._fpw:]
        self._windows.append(frame)
        return frame

    def _analyse(self, ffts, amps) -> ProsodyFrame:
        f0s = [f0 for fft in ffts
               if (f0 := _estimate_f0(fft)) is not None]
        pitch_mean = float(np.mean(f0s)) if f0s else 0.0
        pitch_var = float(np.var(f0s)) if len(f0s) > 1 else 0.0
        jitter = self._jitter(f0s)
        shimmer = self._shimmer(amps)
        silent = sum(1 for a in amps if a < SILENCE_THRESHOLD)
        pause_ratio = silent / len(amps)
        # hesitation_rate: pauses per second (window ≈ 250ms)
        hesitation_rate = pause_ratio * 4.0
        voiced_density = 1.0 - pause_ratio
        speech_rate = voiced_density / self._baseline_density
        self._baseline_density = 0.95 * self._baseline_density + 0.05 * voiced_density
        energy_db = _amp_db(float(np.mean(amps)))
        return ProsodyFrame(
            pitch_mean_hz=round(pitch_mean, 2),
            pitch_variance=round(pitch_var, 2),
            jitter_pct=round(jitter, 3),
            shimmer_pct=round(shimmer, 3),
            hesitation_rate=round(hesitation_rate, 3),
            energy_db=round(energy_db, 1),
            speech_rate_norm=round(speech_rate, 3),
        )

    @staticmethod
    def _jitter(f0s: list[float]) -> float:
        if len(f0s) < 2:
            return 0.0
        diffs = [abs(f0s[i] - f0s[i-1]) for i in range(1, len(f0s))]
        mean = sum(f0s) / len(f0s)
        return (sum(diffs) / len(diffs)) / mean * 100.0 if mean else 0.0

    @staticmethod
    def _shimmer(amps: list[float]) -> float:
        if len(amps) < 2:
            return 0.0
        diffs = [abs(amps[i] - amps[i-1]) for i in range(1, len(amps))]
        mean = sum(amps) / len(amps)
        return (sum(diffs) / len(diffs)) / mean * 100.0 if mean else 0.0

    @property
    def recent_windows(self) -> list[ProsodyFrame]:
        return list(self._windows)

    def clear(self) -> None:
        self._pending_fft.clear()
        self._pending_amp.clear()
        self._windows.clear()
