"""face_recall/renderer.py — HUD card renderer for FaceRecall.

Converts a FaceRecallResult into a HUD render dict.
Applies display suppression rules:
  - No face detected → brief error card (2.5s)
  - Face detected, no match → grey no-match card (2.5s)
  - Match found → full contact card (5s) with confidence color

Confidence color coding:
  >= 85%  → green  (high confidence)
  70-84%  → yellow (medium confidence)
  65-69%  → orange (low confidence, at threshold)
"""
from __future__ import annotations

from typing import Optional

from .schema import FaceRecallResult

# Minimum face detection confidence to attempt matching at all
MIN_FRAME_CONFIDENCE = 0.40


class FaceRecallRenderer:
    """Converts a FaceRecallResult into a HUD card dict."""

    def render(self, result: Optional[FaceRecallResult]) -> Optional[dict]:
        """Return a HUD card dict, or None if nothing to display."""
        if result is None:
            return None
        # Suppress if frame quality is too poor even for a no-face card
        if result.frame_confidence < MIN_FRAME_CONFIDENCE and not result.no_face:
            return None
        return result.to_hud_card()
