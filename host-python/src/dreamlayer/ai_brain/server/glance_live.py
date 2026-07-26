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
  read (read text) · math (an equation → LaTeX) · sky (name what's above) ·
  depth (how far) · segment (isolate one thing).

Person is deliberately NOT a candidate here: the live path defers every face to
the Social Lens (person_guard), exactly as the phone look does — the arbiter
must never try to identify a stranger.

Depth / sky / segment became candidates in the Tier-1 perception pass
(2026-07-23). They were unreachable before for a real reason and it wasn't
policy: the live perceptor emitted only text_density + has_object, so no scene
could ever justify them. Now that the frame yields repetition, bands, darkness,
point-lights and blur — and the phone forwards what its own detector already
sees — each has an honest cue to bid on. `find` is still NOT a candidate: it
needs the nouns you're hunting, which no bare frame supplies.
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
        # Strong horizontal banding IS print, even at a modest density score: the
        # density metric is a mean gradient, so fine type on white under-reads
        # relative to how readable it is. Using the band cue too is what lets a
        # photographed page fire Read instead of falling through (Tier 1).
        banded = (reading.sig("bands", 0) or 0) >= 10
        if reading.scene in ("text", "screen") and (density >= 0.2 or (banded and density >= 0.1)):
            s = 0.62 if (density >= 0.5 or banded) else 0.55
            # Tier 2: head tipped DOWN over text is someone reading something in
            # their hands — the clearest non-verbal "read this" there is.
            down = ctx.tilt_deg <= -20.0
            if down:
                s = min(1.0, s + 0.12)
            return LensBid(self.lens, self.label, s, "read",
                           reason="text in your hands" if down else "text to read")
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


class DepthCandidate(LensCandidate):
    """How far is that. Bids when the wearer is MOVING (a blurred frame is the
    honest signal for walking) and something is in front of them — the mobility
    moment, where distance is the question and reading is not."""
    lens, label = "depth", "How far"

    def bid(self, reading, ctx):
        if not reading.sig("moving"):
            return None
        density = reading.sig("text_density", 0.0) or 0.0
        if reading.scene in ("object", "unknown") and density < 0.28:
            return LensBid(self.lens, self.label, 0.58, "depth",
                           reason="you're moving — distance matters")
        return None


class SkyCandidate(LensCandidate):
    """Look up and the sky is the whole intent. Bids high because the scene cue
    (a dark field with a few point lights and no text) is unambiguous."""
    lens, label = "sky", "Name the sky"

    def bid(self, reading, ctx):
        night = ctx.hour < 0 or ctx.hour >= 19 or ctx.hour < 6
        up = ctx.tilt_deg >= 30.0            # Tier 2: the head is pointed UP
        if reading.scene == "sky":
            # tilting up at night is about as unambiguous as intent gets
            s = 0.9 if (up and night) else 0.8
            return LensBid(self.lens, self.label, s, "sky",
                           reason="you looked up at the night sky" if up
                                  else "the night sky is in view")
        # a dark frame the cue engine wasn't sure about, but you ARE looking up,
        # at night — trust the posture over the pixels
        if up and night and (reading.sig("text_density", 0.0) or 0.0) < 0.12:
            return LensBid(self.lens, self.label, 0.5, "sky",
                           reason="you looked up")
        return None


class SegmentCandidate(LensCandidate):
    """What exactly am I pointing at. A deliberately WEAK bidder: it earns a place
    in the chooser on a cluttered scene but should never outrank identify — the
    mask is a refinement of a look, not usually the point of one."""
    lens, label = "segment", "Isolate it"

    def bid(self, reading, ctx):
        items = reading.sig("items", 0) or 0
        if reading.scene in ("shelf", "object") and items >= 3:
            return LensBid(self.lens, self.label, 0.3, "segment",
                           reason="a cluttered scene to separate")
        return None


# Map a RUN lens (the key look_lens executes) back to the CANDIDATE lens key the
# arbiter learns on, so a chooser pick reinforces the right candidate. The Read
# candidate's key is "read" but it runs the "doc" lens — without this, teaching
# "doc" would never boost the "read" candidate and the learning would be dead.
TEACH_LENS = {"doc": "read", "math": "math", "depth": "depth",
              "sky": "sky", "segment": "segment"}


# The live arbiter's candidates — only lenses WorldLensHost can run.
LIVE_CANDIDATES = [
    TasteLensCandidate(),   # a shelf / menu → compare      (now reachable: `items`)
    RosettaCandidate(),     # foreign text → translate
    ReadCandidate(),        # text → read
    MathCandidate(),        # text → an equation
    SkyCandidate(),         # a dark field + point lights → name the sky
    DepthCandidate(),       # you're moving, something ahead → how far
    SegmentCandidate(),     # a cluttered scene → isolate (weak; chooser-only)
    JunoCandidate(),        # an object → identify (and the weak text fallback)
]
# NOT a candidate, on purpose: `find`. It needs the NOUNS you're looking for, and
# nothing in a bare frame supplies them — auto-firing it would be guessing. It
# becomes reachable when spoken intent lands ("where are my keys" → find, with the
# terms taken from what you actually said), which is the next tier of this work.


def build_live_arbiter(priors_path: Optional[str] = None) -> GlanceArbiter:
    """The Glance Arbiter for the live path, learning per-scene priors to
    `priors_path` (a small JSON beside the vault; in-memory when None)."""
    return GlanceArbiter(candidates=LIVE_CANDIDATES, priors_path=priors_path)
