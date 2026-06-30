"""lie_lens/au_detector.py — Facial Action Unit detection (17 AUs).

Simulates OpenFace MobileNetV3 INT8 on the Halo NPU.
Produces AU activations + micro-expression classification.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .schema import AUFrame

NUM_AUS = 17

# Micro-expression labels from CASME II dataset
MICRO_EXP_LABELS = [
    "neutral", "happiness", "surprise", "fear",
    "disgust", "contempt", "anger", "repression", "tense",
]

# AU combinations that CASME II + FACS associate with deception
DECEPTION_AU_COMBOS = [
    {12, 14},    # lip corner pull + dimpler (false smile)
    {1, 4},      # inner brow raise + brow lower (fear-masked)
    {20, 26},    # lip stretcher + jaw drop (surprise suppression)
    {7, 17},     # lid tightener + chin raiser (contempt micro)
]


class AUDetector:
    """Detects 17 facial action units from a camera frame.

    Parameters
    ----------
    npu_fn : callable, optional
        Override for testing. Signature: (frame: np.ndarray) -> dict | None
    """

    def __init__(self, npu_fn=None):
        self._npu = npu_fn or self._mock_npu

    def detect(self, frame: Optional[np.ndarray]) -> Optional[AUFrame]:
        """Return AUFrame or None if detection fails."""
        if frame is None:
            return None
        result = self._npu(frame)
        if result is None or "aus" not in result:
            return None
        aus = [max(0.0, min(1.0, float(v))) for v in result["aus"]]
        # Pad or truncate to exactly NUM_AUS
        aus = (aus + [0.0] * NUM_AUS)[:NUM_AUS]
        label = result.get("micro_exp", "neutral")
        conf = float(result.get("micro_exp_confidence", 0.5))
        return AUFrame(aus=aus, micro_exp_label=label,
                       micro_exp_confidence=conf)

    def detect_combo_deception(self, au_frame: AUFrame,
                                threshold: float = 0.4) -> bool:
        """Return True if any known deception AU combo is active above threshold."""
        active = {
            i + 1 for i, v in enumerate(au_frame.aus) if v >= threshold
        }
        return any(combo.issubset(active) for combo in DECEPTION_AU_COMBOS)

    @staticmethod
    def _mock_npu(frame: np.ndarray) -> Optional[dict]:
        rng = np.random.default_rng(seed=int(abs(frame.sum())) % 2**31)
        aus = rng.uniform(0, 0.3, NUM_AUS).tolist()
        label = rng.choice(MICRO_EXP_LABELS)
        return {"aus": aus, "micro_exp": label, "micro_exp_confidence": 0.6}
