"""truth_lens/au_detector.py — Facial Action Unit detector.

Wraps the on-device OpenFace MobileNetV3 INT8 model.
Produces 17 AU activation values from a camera frame.

AU index mapping (FACS):
  0  AU1   Inner brow raise
  1  AU2   Outer brow raise
  2  AU4   Brow lowerer
  3  AU5   Upper lid raiser
  4  AU6   Cheek raiser
  5  AU7   Lid tightener
  6  AU9   Nose wrinkler
  7  AU10  Upper lip raiser
  8  AU12  Lip corner puller (smile)
  9  AU14  Dimpler
  10 AU15  Lip corner depressor
  11 AU17  Chin raiser
  12 AU20  Lip stretcher
  13 AU23  Lip tightener
  14 AU24  Lip pressor
  15 AU25  Lips part
  16 AU26  Jaw drop
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .schema import AUFrame

# AUs that most strongly correlate with micro-expression stress
STRESS_AUS = {2, 3, 5, 13, 14}   # AU4, AU5, AU7, AU23, AU24


class AUDetector:
    """Extracts 17 AU activations from a camera frame.

    Stub implementation: derives AU values deterministically from the
    frame content so tests run without hardware.
    """

    def process(self, au_frame: Optional[AUFrame]) -> Optional[AUFrame]:
        """Refine AU values in-place (no-op in stub; hooks into NPU in prod)."""
        return au_frame

    def micro_expression_score(self, au_frame: AUFrame) -> float:
        """0-1 micro-expression stress score from AU activations."""
        if not au_frame or not au_frame.au_values:
            return 0.0
        stress_vals = [au_frame.au_values[i] for i in STRESS_AUS
                       if i < len(au_frame.au_values)]
        if not stress_vals:
            return 0.0
        return min(sum(stress_vals) / len(stress_vals) * 2.5, 1.0)

    def compute_au_zscores(
        self,
        au_frame: AUFrame,
        baseline_mean: list[float],
        baseline_std: list[float],
    ) -> list[float]:
        """Z-score each AU value against the per-contact baseline."""
        z = []
        for i, v in enumerate(au_frame.au_values):
            std = baseline_std[i] if i < len(baseline_std) else 0.1
            mean = baseline_mean[i] if i < len(baseline_mean) else 0.0
            z.append((v - mean) / max(std, 0.01))
        return z
