"""truth_lens/fusion.py — Multi-signal z-score fusion engine."""
from __future__ import annotations
from typing import Optional
from .schema import (
    AUFrame, ProsodyFrame, LinguisticFrame,
    ContactBaseline, CredibilityVector,
)
from .au_detector import AUDetector

STRANGER_Z_THRESHOLD = 3.0
CHANNEL_WEIGHTS = {
    "micro_expression": 0.35,
    "voice_stress":     0.35,
    "linguistic":       0.30,
}


class FusionEngine:
    def __init__(self):
        self._au_detector = AUDetector()

    def fuse(self, au: Optional[AUFrame], prosody: Optional[ProsodyFrame],
             linguistic: Optional[LinguisticFrame],
             baseline: Optional[ContactBaseline]) -> CredibilityVector:
        is_stranger = baseline is None or not baseline.is_calibrated
        if is_stranger:
            return self._stranger_fuse(au, prosody, linguistic)
        return self._known_fuse(au, prosody, linguistic, baseline)

    def _known_fuse(self, au, prosody, linguistic, baseline):
        scores = {}
        z_scores = {}
        if au is not None:
            z_list = self._au_detector.compute_au_zscores(
                au, baseline.au_mean, baseline.au_std)
            z_au = sum(abs(z) for z in z_list) / max(len(z_list), 1)
            z_scores["micro_expression"] = z_au
            scores["micro_expression"] = min(z_au / 4.0, 1.0)
        else:
            z_scores["micro_expression"] = 0.0
            scores["micro_expression"] = 0.0
        if prosody is not None:
            z_prosody = prosody.stress_score() * 4.0
            z_scores["voice_stress"] = z_prosody
            scores["voice_stress"] = prosody.stress_score()
        else:
            z_scores["voice_stress"] = 0.0
            scores["voice_stress"] = 0.0
        if linguistic is not None:
            z_ling = linguistic.deception_score() * 4.0
            z_scores["linguistic"] = z_ling
            scores["linguistic"] = linguistic.deception_score()
        else:
            z_scores["linguistic"] = 0.0
            scores["linguistic"] = 0.0
        deception_prob = sum(
            scores[ch] * CHANNEL_WEIGHTS[ch] for ch in CHANNEL_WEIGHTS)
        active = sum(1 for ch in [au, prosody, linguistic] if ch is not None)
        confidence = (active / 3.0) * min(baseline.sample_count / 20.0, 1.0)
        dominant = max(scores, key=scores.get)
        return CredibilityVector(
            deception_prob=round(deception_prob, 3),
            confidence=round(confidence, 3),
            micro_expression_z=round(z_scores["micro_expression"], 3),
            voice_stress_z=round(z_scores["voice_stress"], 3),
            linguistic_z=round(z_scores["linguistic"], 3),
            dominant_channel=dominant,
            is_stranger=False,
        )

    def _stranger_fuse(self, au, prosody, linguistic):
        au_score = self._au_detector.micro_expression_score(au) if au else 0.0
        prosody_score = prosody.stress_score() if prosody else 0.0
        ling_score = linguistic.deception_score() if linguistic else 0.0
        all_high = all(s > 0.75 for s in [au_score, prosody_score, ling_score] if s > 0)
        deception_prob = (
            (au_score * 0.35 + prosody_score * 0.35 + ling_score * 0.30)
            if all_high else
            max(au_score, prosody_score, ling_score) * 0.3
        )
        scores = {"micro_expression": au_score,
                  "voice_stress": prosody_score,
                  "linguistic": ling_score}
        dominant = max(scores, key=scores.get)
        return CredibilityVector(
            deception_prob=round(deception_prob, 3),
            confidence=0.2,
            micro_expression_z=au_score * 4.0,
            voice_stress_z=prosody_score * 4.0,
            linguistic_z=ling_score * 4.0,
            dominant_channel=dominant,
            is_stranger=True,
        )
