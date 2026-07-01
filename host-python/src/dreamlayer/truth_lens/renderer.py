"""truth_lens/renderer.py — HUD card renderer for Truth Lens."""
from __future__ import annotations
from typing import Optional
from .schema import TruthLensResult, CredibilityVector

DISPLAY_THRESHOLD = 0.30
CONFIDENCE_THRESHOLD = 0.25


class TruthLensRenderer:
    def render(self, result: Optional[TruthLensResult]) -> Optional[dict]:
        if result is None:
            return None
        c = result.credibility
        if c.confidence < CONFIDENCE_THRESHOLD and not c.is_stranger:
            return None
        if c.deception_prob < DISPLAY_THRESHOLD:
            return None
        card = result.to_hud_card()
        card["renderer_hints"] = self._build_hints(c)
        return card

    def _build_hints(self, c: CredibilityVector) -> dict:
        return {
            "chromatic_aberration": c.voice_stress_z > 2.0,
            "chromatic_strength": min(c.voice_stress_z / 10.0, 0.02) if c.voice_stress_z > 2.0 else 0.0,
            "particle_color": c.hud_color,
            "particle_density": round(c.confidence * 0.5, 2),
            "particle_origin": "temple",
            "bone_conduction_delay_ms": (int(c.linguistic_z * 5) if c.linguistic_z > 1.5 else 0),
            "auto_dismiss_ms": 5000,
            "opacity": 0.9 if c.confidence >= CONFIDENCE_THRESHOLD else 0.4,
        }
