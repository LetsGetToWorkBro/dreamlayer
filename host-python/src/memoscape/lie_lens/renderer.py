"""lie_lens/renderer.py — HUD card renderer for Lie Lens.

Maps to Stage 7 (Sub-perceptual renderer) in the Lua spec:
  - Chromatic aberration hint (voice stress z > 2.0)
  - Particle system color (from CredibilityVector.hud_color)
  - Bone conduction audio delay hint (linguistic z-score driven)
  - LieLensCard dict output (sent to the existing HUD renderer)

This module is pure data — it produces render instruction dicts
that the hardware bridge translates into display commands.
"""
from __future__ import annotations

from typing import Optional

from .schema import LieLensResult, CredibilityVector

# Minimum deception probability before any overlay is shown
DISPLAY_THRESHOLD = 0.30

# Minimum confidence before showing a non-grey card
CONFIDENCE_THRESHOLD = 0.25


class LieLensRenderer:
    """Converts a LieLensResult into HUD render instructions."""

    def render(self, result: Optional[LieLensResult],
               origin: Optional[dict] = None) -> Optional[dict]:
        """Return a HUD card dict, or None if nothing should be displayed.

        Halo Cinema v1: emits the TruthLensCard 9-ring gauge (one ring per
        analysis stage, filled by stage confidence, colored by signal
        direction) with a Truth Ripple entry from the eye landmark
        `origin`. The legacy flat LieLensCard payload remains available
        via result.to_hud_card() for downstream consumers.
        """
        if result is None:
            return None

        c = result.credibility

        # Suppress display if confidence is too low
        if c.confidence < CONFIDENCE_THRESHOLD and not c.is_stranger:
            return None

        # Suppress display if score is below threshold
        if c.deception_prob < DISPLAY_THRESHOLD:
            return None

        card = result.to_gauge_card(origin=origin)

        # Enrich renderer hints
        card["renderer_hints"] = self._build_hints(c)

        return card

    def _build_hints(self, c: CredibilityVector) -> dict:
        return {
            # Chromatic aberration on face edges (voice stress indicator)
            "chromatic_aberration": c.voice_stress_z > 2.0,
            "chromatic_strength": min(c.voice_stress_z / 10.0, 0.02)
            if c.voice_stress_z > 2.0 else 0.0,
            # Particle system
            "particle_color": c.hud_color,
            "particle_density": round(c.confidence * 0.5, 2),
            "particle_origin": "temple",
            # Bone conduction delay
            "bone_conduction_delay_ms": (
                int(c.linguistic_z * 5)
                if c.linguistic_z > 1.5 else 0
            ),
            # Display behavior
            "auto_dismiss_ms": 5000,
            "opacity": 0.9 if c.confidence >= CONFIDENCE_THRESHOLD else 0.4,
        }
