"""social_lens/timbre.py — every contact has a visual timbre.

A timbre is a small, consistent 12-point waveform derived entirely from
a contact's prosody baseline (the per-contact voice statistics the Truth
Lens narrative store already learns). The same person always draws the
same shape; two different voices draw visibly different shapes. Nothing
is stored beyond what the baseline already holds, and the signature is
one-way — you cannot recover a voice from twelve small integers.

Construction: the baseline's normalized voice statistics seed three
harmonics (their amplitudes, frequencies, and phases), the sum is
sampled at 12 points and quantized to 0..15 around a center of 8.
Deterministic, dependency-free, stable across sessions.
"""
from __future__ import annotations

import math

POINTS = 12
CENTER = 8
AMP_MAX = 7          # points live in [1, 15]

# plausible physical ranges for normalization (match prosody.py's world)
_RANGES = {
    "pitch_mean_hz":   (80.0, 320.0),
    "pitch_variance":  (0.0, 600.0),
    "jitter_pct":      (0.0, 6.0),
    "shimmer_pct":     (0.0, 10.0),
    "hesitation_rate": (0.0, 3.0),
    "pause_ratio":     (0.0, 0.8),
    "speech_rate_norm": (0.5, 2.0),
    "energy_db":       (-40.0, 0.0),
}


def _norm(prosody_mean: dict, key: str) -> float:
    lo, hi = _RANGES[key]
    v = float(prosody_mean.get(key, (lo + hi) / 2.0))
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def timbre_signature(prosody_mean: dict) -> list[int]:
    """12 quantized samples of the contact's harmonic identity."""
    pitch = _norm(prosody_mean, "pitch_mean_hz")
    var = _norm(prosody_mean, "pitch_variance")
    jit = _norm(prosody_mean, "jitter_pct")
    shm = _norm(prosody_mean, "shimmer_pct")
    hes = _norm(prosody_mean, "hesitation_rate")
    pau = _norm(prosody_mean, "pause_ratio")
    rate = _norm(prosody_mean, "speech_rate_norm")
    eng = _norm(prosody_mean, "energy_db")

    # three harmonics: the fundamental is the person's pitch identity,
    # the second carries texture (jitter/shimmer), the third cadence
    harmonics = [
        (0.55 + 0.45 * eng,  1.0 + round(pitch * 2),  2 * math.pi * pitch),
        (0.30 + 0.50 * shm,  2.0 + round(var * 2),    2 * math.pi * jit),
        (0.20 + 0.45 * hes,  3.0 + round(rate * 2),   2 * math.pi * pau),
    ]
    total_amp = sum(a for a, _, _ in harmonics)

    points: list[int] = []
    for i in range(POINTS):
        t = i / POINTS
        s = sum(a * math.sin(2 * math.pi * f * t + phi)
                for a, f, phi in harmonics) / total_amp
        points.append(max(1, min(15, CENTER + round(s * AMP_MAX))))
    return points


def signature_distance(a: list[int], b: list[int]) -> int:
    """How differently two voices draw (L1 over the 12 points)."""
    return sum(abs(x - y) for x, y in zip(a, b))
