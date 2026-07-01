"""truth_lens/au_detector.py — Facial Action Unit detector."""
from __future__ import annotations
from typing import Optional
from .schema import AUFrame

STRESS_AUS = {2, 3, 5, 13, 14}


class AUDetector:
    def process(self, au_frame: Optional[AUFrame]) -> Optional[AUFrame]:
        return au_frame

    def micro_expression_score(self, au_frame: AUFrame) -> float:
        if not au_frame or not au_frame.au_values:
            return 0.0
        stress_vals = [au_frame.au_values[i] for i in STRESS_AUS
                       if i < len(au_frame.au_values)]
        if not stress_vals:
            return 0.0
        return min(sum(stress_vals) / len(stress_vals) * 2.5, 1.0)

    def compute_au_zscores(self, au_frame: AUFrame,
                           baseline_mean: list[float],
                           baseline_std: list[float]) -> list[float]:
        z = []
        for i, v in enumerate(au_frame.au_values):
            std = baseline_std[i] if i < len(baseline_std) else 0.1
            mean = baseline_mean[i] if i < len(baseline_mean) else 0.0
            z.append((v - mean) / max(std, 0.01))
        return z
