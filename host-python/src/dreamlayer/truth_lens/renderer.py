"""truth_lens/renderer.py — HUD card renderer for Lie Lens.

Maps to Stage 7 (Sub-perceptual renderer) in the Lua spec:
  - Chromatic aberration hint (voice stress z > 2.0)
  - Particle system color (from CredibilityVector.hud_color)
  - Bone conduction audio delay hint (linguistic z-score driven)
  - TruthLensCard dict output (sent to the existing HUD renderer)

This module is pure data — it produces render instruction dicts
that the hardware bridge translates into display commands.
"""
from __future__ import annotations

from typing import Optional

from .schema import TruthLensResult, CredibilityVector

# Minimum deception probability before any overlay is shown.
#
# 0.40 because that is where `CredibilityVector.label` stops saying CREDIBLE. At
# 0.30 the gate and the vocabulary disagreed, and the 0.30–0.40 band drew a card
# whose own verdict word was "CREDIBLE" — an overlay announcing that nothing is
# the matter. On the measured calm case (voice stress 0.40, linguistic 0.325)
# that lands at 0.365, i.e. an ordinary sentence from an ordinary speaker drew a
# gauge, and drew it again on the next sentence, and the next. A readout that
# appears on every utterance is one the wearer learns to stop seeing, which costs
# them the reads that actually matter.
#
# Suppressing the reassuring read here loses nothing, because the caller that
# genuinely wants it does not come through the renderer: Discernment calls
# `TruthLens.assess()`, which is documented as deliberately ungated for exactly
# this reason ("credible delivery is exactly what turns a wrong claim into an
# honest mistake rather than a lie"). This constant governs the HUD overlay only.
#
# Pinned to the vocabulary by test_the_gauge_never_draws_a_reassuring_verdict, so
# the two cannot drift apart again.
DISPLAY_THRESHOLD = 0.40

# Minimum confidence before showing a non-grey card
CONFIDENCE_THRESHOLD = 0.25


class TruthLensRenderer:
    """Converts a TruthLensResult into HUD render instructions."""

    def render(self, result: Optional[TruthLensResult],
               origin: Optional[dict] = None) -> Optional[dict]:
        """Return a HUD card dict, or None if nothing should be displayed.

        Halo Cinema v1: emits the TruthLensCard 9-ring gauge (one ring per
        analysis stage, filled by stage confidence, colored by signal
        direction) with a Truth Ripple entry from the eye landmark
        `origin`. The legacy flat TruthLensCard payload remains available
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
