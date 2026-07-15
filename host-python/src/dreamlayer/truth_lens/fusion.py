"""truth_lens/fusion.py — Multi-signal z-score fusion engine.

Maps to the Phi-3-mini-4k LoRA fusion stage.
Computes z-scores for each channel against the per-contact baseline,
then combines them into a CredibilityVector.

Two modes
---------
  Known contact  : z-scores vs personal baseline → higher accuracy
  Stranger        : conservative absolute thresholds (no baseline)
"""
from __future__ import annotations

from typing import Optional

from .schema import (
    AUFrame, ProsodyFrame, LinguisticFrame,
    ContactBaseline, CredibilityVector,
)
from .au_detector import AUDetector

# Stranger mode: only flag if ALL channels exceed this z-score
STRANGER_Z_THRESHOLD = 3.0

# The micro-expression (AU) channel is a DEVICE SEAM not yet backed by a real
# facial-action-unit detector: today au_detector produces frame-hash noise, not
# a measured signal (audit 2026-07-14). A fabricated channel must never drive a
# deception verdict or inflate confidence, so its weight is 0 and it is not
# counted as an active channel — it is reported for display only. Flip this to
# True (and give AUDetector a real implementation) the day a genuine detector
# lands; the fusion plumbing already exists behind it.
AU_CHANNEL_REAL = False

# Known-contact weights for final deception_prob. The AU weight is gated on the
# channel being real; the effective weights are renormalised over the channels
# that actually contribute, so the two real channels are not silently diluted.
CHANNEL_WEIGHTS = {
    "micro_expression": 0.35 if AU_CHANNEL_REAL else 0.0,
    "voice_stress":     0.35,
    "linguistic":       0.30,
}


def _effective_weights() -> dict:
    """CHANNEL_WEIGHTS renormalised to sum to 1 over the contributing channels,
    so dropping the synthetic AU channel does not scale the verdict down."""
    total = sum(CHANNEL_WEIGHTS.values()) or 1.0
    return {ch: w / total for ch, w in CHANNEL_WEIGHTS.items()}


def _avg_abs_z(frame, mean: dict, std: dict, names) -> float:
    """Average absolute z-score of a frame's features against the per-contact
    baseline — the real personalization the module claims. Falls back to 0 for
    a feature the baseline hasn't seen yet."""
    zs = []
    for name in names:
        if name not in mean:
            continue
        s = std.get(name, 0.1) or 0.1
        zs.append(abs((getattr(frame, name) - mean[name]) / s))
    return sum(zs) / len(zs) if zs else 0.0


_PROSODY_FEATURES = ("pitch_mean_hz", "pitch_variance", "jitter_pct",
                     "shimmer_pct", "hesitation_rate", "pause_ratio",
                     "speech_rate_norm", "energy_db")
_LINGUISTIC_FEATURES = ("hedging_rate", "first_person_rate",
                        "complexity_score", "negation_rate")


class FusionEngine:
    """Combines AU, prosody, and linguistic signals into a CredibilityVector."""

    def __init__(self):
        self._au_detector = AUDetector()

    def fuse(
        self,
        au: Optional[AUFrame],
        prosody: Optional[ProsodyFrame],
        linguistic: Optional[LinguisticFrame],
        baseline: Optional[ContactBaseline],
    ) -> CredibilityVector:
        """Produce a CredibilityVector from available signals."""
        is_stranger = baseline is None or not baseline.is_calibrated

        if is_stranger:
            return self._stranger_fuse(au, prosody, linguistic)
        assert baseline is not None   # is_stranger is False only for a real baseline
        return self._known_fuse(au, prosody, linguistic, baseline)

    # ------------------------------------------------------------------
    # Known-contact fusion
    # ------------------------------------------------------------------

    def _known_fuse(
        self,
        au: Optional[AUFrame],
        prosody: Optional[ProsodyFrame],
        linguistic: Optional[LinguisticFrame],
        baseline: ContactBaseline,
    ) -> CredibilityVector:
        scores = {}
        z_scores = {}

        # AU channel — neutral while synthetic. Zeroing its WEIGHT kept AU out of
        # the verdict, but the score/z were still computed from live detector
        # noise, so `dominant_channel` could headline "micro_expression" and a
        # nonzero micro_expression_z could surface on the card — a synthetic
        # signal shown as real (re-audit 2026-07-15). Skip the compute entirely
        # until the channel is real; it then contributes nowhere, display too.
        if au is not None and AU_CHANNEL_REAL:
            z_list = self._au_detector.compute_au_zscores(
                au, baseline.au_mean, baseline.au_std
            )
            z_au = sum(abs(z) for z in z_list) / max(len(z_list), 1)
            z_scores["micro_expression"] = z_au
            scores["micro_expression"] = min(z_au / 4.0, 1.0)
        else:
            z_scores["micro_expression"] = 0.0
            scores["micro_expression"] = 0.0

        # Prosody channel — a REAL per-feature z-score against the personal
        # baseline (the personalization the module advertises), blended with the
        # absolute heuristic so a fresh baseline still reads sensibly.
        if prosody is not None:
            z_prosody = _avg_abs_z(prosody, baseline.prosody_mean,
                                   baseline.prosody_std, _PROSODY_FEATURES)
            z_scores["voice_stress"] = z_prosody
            scores["voice_stress"] = max(prosody.stress_score(),
                                         min(z_prosody / 4.0, 1.0))
        else:
            z_scores["voice_stress"] = 0.0
            scores["voice_stress"] = 0.0

        # Linguistic channel — same, against the linguistic baseline.
        if linguistic is not None:
            z_ling = _avg_abs_z(linguistic, baseline.linguistic_mean,
                                baseline.linguistic_std, _LINGUISTIC_FEATURES)
            z_scores["linguistic"] = z_ling
            scores["linguistic"] = max(linguistic.deception_score(),
                                       min(z_ling / 4.0, 1.0))
        else:
            z_scores["linguistic"] = 0.0
            scores["linguistic"] = 0.0

        # Weighted deception probability over the channels that actually
        # contribute (the synthetic AU channel has weight 0 until it is real).
        weights = _effective_weights()
        deception_prob = sum(scores[ch] * weights[ch] for ch in weights)

        # Confidence: how many REAL channels contributed + baseline calibration.
        # The AU channel does not count while it is synthetic, so noise can't
        # inflate confidence.
        real_channels: list = [prosody, linguistic]
        if AU_CHANNEL_REAL:
            real_channels.append(au)
        active = sum(1 for ch in real_channels if ch is not None)
        confidence = (active / len(real_channels)) * min(
            baseline.sample_count / 20.0, 1.0)

        dominant = max(scores, key=lambda k: scores[k])

        return CredibilityVector(
            deception_prob=round(deception_prob, 3),
            confidence=round(confidence, 3),
            micro_expression_z=round(z_scores["micro_expression"], 3),
            voice_stress_z=round(z_scores["voice_stress"], 3),
            linguistic_z=round(z_scores["linguistic"], 3),
            dominant_channel=dominant,
            is_stranger=False,
        )

    # ------------------------------------------------------------------
    # Stranger fusion (conservative — no baseline)
    # ------------------------------------------------------------------

    def _stranger_fuse(
        self,
        au: Optional[AUFrame],
        prosody: Optional[ProsodyFrame],
        linguistic: Optional[LinguisticFrame],
    ) -> CredibilityVector:
        au_raw = (self._au_detector.micro_expression_score(au)
                  if au else 0.0)
        # the synthetic AU channel must not drive a stranger verdict either
        au_score = au_raw if AU_CHANNEL_REAL else 0.0
        prosody_score = prosody.stress_score() if prosody else 0.0
        ling_score = linguistic.deception_score() if linguistic else 0.0

        # Only alert if ALL contributing channels are elevated (conservative).
        verdict_scores = [prosody_score, ling_score]
        if AU_CHANNEL_REAL:
            verdict_scores.append(au_score)
        all_high = bool(verdict_scores) and all(
            s > 0.75 for s in verdict_scores if s > 0)

        deception_prob = (
            (au_score * 0.35 + prosody_score * 0.35 + ling_score * 0.30)
            if all_high else
            max([0.0] + verdict_scores) * 0.3  # dampened
        )

        scores = {"micro_expression": au_score,
                  "voice_stress": prosody_score,
                  "linguistic": ling_score}
        dominant = max(scores, key=lambda k: scores[k])

        return CredibilityVector(
            deception_prob=round(deception_prob, 3),
            confidence=0.2,         # always low confidence for strangers
            micro_expression_z=au_score * 4.0,
            voice_stress_z=prosody_score * 4.0,
            linguistic_z=ling_score * 4.0,
            dominant_channel=dominant,
            is_stranger=True,
        )
