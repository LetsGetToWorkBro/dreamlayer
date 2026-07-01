"""social_lens/renderer.py — HUD card renderer for Social Lens."""
from __future__ import annotations
from typing import Optional
from .schema import SocialLensResult

MIN_FRAME_CONFIDENCE = 0.40


class SocialLensRenderer:
    def render(self, result: Optional[SocialLensResult]) -> Optional[dict]:
        if result is None:
            return None
        if result.frame_confidence < MIN_FRAME_CONFIDENCE and not result.no_face:
            return None
        return result.to_hud_card()
