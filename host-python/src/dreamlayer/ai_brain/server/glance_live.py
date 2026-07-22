"""ai_brain/server/glance_live.py — the live path's Glance Arbiter wiring.

The glasses never make you pick a lens: on a look, the Glance Arbiter
(orchestrator/glance.py) reads what's in view, lets each lens *bid*, and either
fires the clear winner or offers a one-tap chooser when it's genuinely
ambiguous. That whole system lived only on the Orchestrator (which the shipped
Brain never builds), so the Live Lens never got it — it had a manual dropdown
instead. This module builds the SAME arbiter for the live host (WorldLensHost),
with a candidate set restricted to the lenses that host can actually run.

Only lenses WorldLensHost can execute may bid:
  juno (identify) · taste (compare a shelf/menu) · translate (foreign text) ·
  read (read text aloud/plain) · math (an equation → LaTeX).

Person is deliberately NOT a candidate here: the live path defers every face to
the Social Lens (person_guard), exactly as the phone look does — the arbiter
must never try to identify a stranger. Depth / find / sky stay DELIBERATE lenses
(they need a distance intent, search terms, or your location), reached through
the manual override, not auto-fired from a bare frame.
"""
from __future__ import annotations

from typing import Optional

from ...orchestrator.glance import (
    GlanceArbiter, JunoCandidate, LensBid, LensCandidate, RosettaCandidate,
    TasteLensCandidate,
)


class ReadCandidate(LensCandidate):
    """Read the text in view — the default for a page/sign. Maps to the doc
    lens (Surya layout read, with the on-device OCR ladder behind it)."""
    lens, label = "read", "Read it"

    def bid(self, reading, ctx) -> Optional[LensBid]:
        density = reading.sig("text_density", 0.0) or 0.0
        if reading.scene in ("text", "screen") and density >= 0.2:
            # stronger the denser the text; a clear default owner of a page.
            s = 0.62 if density >= 0.5 else 0.55
            return LensBid(self.lens, self.label, s, "read",
                           reason="text to read")
        return None


class MathCandidate(LensCandidate):
    """An equation on the page → LaTeX. Bids just under Read on any text, so a
    plain page fires Read outright but a look that could be either offers a
    two-tap chooser (Read · Math). The arbiter learns which you pick here."""
    lens, label = "math", "Solve the math"

    def bid(self, reading, ctx) -> Optional[LensBid]:
        density = reading.sig("text_density", 0.0) or 0.0
        if reading.scene in ("text", "screen") and density >= 0.2:
            return LensBid(self.lens, self.label, 0.46, "math",
                           reason="could be an equation")
        return None


# The live arbiter's candidates — only lenses WorldLensHost can run.
LIVE_CANDIDATES = [
    TasteLensCandidate(),   # a shelf / menu → compare
    RosettaCandidate(),     # foreign text → translate
    ReadCandidate(),        # text → read
    MathCandidate(),        # text → an equation
    JunoCandidate(),        # an object → identify (and the weak text fallback)
]


def build_live_arbiter(priors_path: Optional[str] = None) -> GlanceArbiter:
    """The Glance Arbiter for the live path, learning per-scene priors to
    `priors_path` (a small JSON beside the vault; in-memory when None)."""
    return GlanceArbiter(candidates=LIVE_CANDIDATES, priors_path=priors_path)
