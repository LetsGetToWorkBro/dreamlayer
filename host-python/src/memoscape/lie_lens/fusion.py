"""lie_lens/fusion.py — Z-score multi-signal fusion → CredibilityVector.

Computes per-dimension z-scores against the contact's stored baseline,
then combines them into a single CredibilityVector via weighted fusion.
In stranger mode (no baseline), uses absolute heuristic thresholds.
"""
from __future__ import annotations

from typing import Optional

from .schema import (
    AUFrame, ProsodyFrame, LinguisticFrame,
    ContactBaseline, CredibilityVector,
)

# Fusion weights (must sum to 1.0)
WEIGHTS = {
    "micro_exp": 0.35,
    "voice_stress": 0.35,
    "linguistic": 0.30,
}

# Minimum windows before confidence is meaningful
MIN_WINDOWS = 4


def _zscore(value: float, mean: float, std: float) -> float:
    """Standardised z-score clamped to [-4, 4]."""
    if std < 1e-6:
        return 0.0
    return max(-4.0, min((value - mean) / std, 4.0))


def _z_to_prob(z: float) -> float:
    """Map z-score to 0-1 anomaly probability (sigmoid-like)."""
    # z=0 → 0.5, z=3 → ~0.95, z=-3 → ~0.05
    import math
    return 1.0 / (1.0 + math.exp(-z * 0.8))


def fuse(
    au_frames: list[AUFrame],
    prosody_frames: list[ProsodyFrame],
    linguistic_frames: list[LinguisticFrame],
    baseline: Optional[ContactBaseline],
    window_count: int,
) -> CredibilityVector:
    """Produce a CredibilityVector from accumulated signal frames."""

    is_stranger = baseline is None or not baseline.is_reliable

    # --- AU z-score ---
    if au_frames:
        au_scores = [f.deception_au_score() for f in au_frames]
        au_mean = sum(au_scores) / len(au_scores)
        if is_stranger:
            micro_z = au_mean * 4.0  # absolute proxy
        else:
            ref_mean = sum(baseline.au_mean) / len(baseline.au_mean)
            ref_std = max(sum(baseline.au_std) / len(baseline.au_std), 0.05)
            micro_z = _zscore(au_mean, ref_mean, ref_std)
    else:
        micro_z = 0.0

    # --- Prosody z-score ---
    if prosody_frames:
        p_scores = [f.stress_score() for f in prosody_frames]
        p_mean = sum(p_scores) / len(p_scores)
        if is_stranger:
            voice_z = p_mean * 4.0
        else:
            ref_mean = baseline.prosody_pitch_mean / 200.0  # normalise
            ref_std = max(baseline.prosody_pitch_std / 200.0, 0.05)
            voice_z = _zscore(p_mean, ref_mean, ref_std)
    else:
        voice_z = 0.0

    # --- Linguistic z-score ---
    if linguistic_frames:
        l_scores = [f.deception_score() for f in linguistic_frames]
        l_mean = sum(l_scores) / len(l_scores)
        if is_stranger:
            ling_z = l_mean * 4.0
        else:
            ref_mean = baseline.linguistic_hedge_mean
            ref_std = 0.1
            ling_z = _zscore(l_mean, ref_mean, ref_std)
    else:
        ling_z = 0.0

    # --- Weighted fusion ---
    micro_prob = _z_to_prob(micro_z)
    voice_prob = _z_to_prob(voice_z)
    ling_prob = _z_to_prob(ling_z)

    deception_prob = (
        WEIGHTS["micro_exp"]   * micro_prob +
        WEIGHTS["voice_stress"] * voice_prob +
        WEIGHTS["linguistic"]   * ling_prob
    )

    # Confidence rises with window count
    confidence = min(window_count / MIN_WINDOWS, 1.0)
    # Halve confidence in stranger mode
    if is_stranger:
        confidence *= 0.5

    # Dominant signal
    contribs = {
        "micro_exp":   WEIGHTS["micro_exp"]   * micro_prob,
        "voice_stress": WEIGHTS["voice_stress"] * voice_prob,
        "linguistic":  WEIGHTS["linguistic"]   * ling_prob,
    }
    dominant = max(contribs, key=contribs.get)

    return CredibilityVector(
        deception_prob=round(deception_prob, 3),
        confidence=round(confidence, 3),
        micro_exp_z=round(micro_z, 2),
        voice_stress_z=round(voice_z, 2),
        linguistic_z=round(ling_z, 2),
        dominant_signal=dominant,
        is_stranger=is_stranger,
        window_count=window_count,
    )
