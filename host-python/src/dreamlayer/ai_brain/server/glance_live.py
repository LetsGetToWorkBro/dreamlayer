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

Sky and segment became candidates in the Tier-1 perception pass: the live
perceptor used to emit only text_density + has_object, so no scene could justify
them. Now the frame yields repetition, banding, darkness and point-lights, and
the phone forwards what its own detector already sees, so each has a real cue.

What a frame CANNOT justify is kept out, which is the whole discipline here:

  find    needs the nouns you are hunting, and no frame supplies them.
  depth   bid on motion blur as a proxy for walking. Sensor noise is itself high
          frequency, so that measurement is of the noise floor — a still frame can
          score "blurrier" than a moving one. Spoken only.
  sky     the pixels of rain on a dark window and of a starfield are the same
          picture, so pixels alone put it in the CHOOSER; only pixels plus a
          camera pointed up at night fire it.
  shelf   a bookshelf and a radiator are one picture to a gradient profile, so it
          comes from the phone's detector seeing several of the same thing.
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
    """How far is that — reached by ASKING, like `find`.

    It bid on a `moving` cue, on the theory that motion blur is the honest signal
    for walking. It is not, once a real sensor is in the loop: blur removes
    high-frequency signal, but sensor noise is added after the blur and is itself
    pure high frequency, so the measurement is of the noise floor. Measured on
    directionally-blurred street frames, a still one at low noise scores HIGHER
    than the same frame blurred 24 px at ISO 800, and normalising by contrast does
    not separate them either. The cue never fired on a real frame, and where it did
    it told a stationary wearer they were walking.

    So it is not a frame bidder at all. It keeps a bid only when the wearer SAID
    so — "how far is that" — which the spoken path executes directly, and which is
    the same honest arrangement `find` has: an intent no frame can justify becomes
    available the moment you say it."""
    lens, label = "depth", "How far"

    def bid(self, reading, ctx):
        if ctx.recent_intent != "depth":
            return None
        return LensBid(self.lens, self.label, 0.7, "depth",
                       reason="you asked how far")


class SkyCandidate(LensCandidate):
    """Look up and the sky is the whole intent. Bids high because the scene cue
    (a dark field with a few point lights and no text) is unambiguous."""
    lens, label = "sky", "Name the sky"

    def bid(self, reading, ctx):
        # An UNKNOWN hour is not night. `ctx.hour < 0` is the "we don't know"
        # sentinel (GlanceContext defaults to -1, and not every caller sets it), so
        # treating it as night was a fail-OPEN in a codebase that fails closed
        # everywhere else — it handed the astronomy lens a free pass whenever the
        # clock was unavailable.
        night = 0 <= ctx.hour and (ctx.hour >= 19 or ctx.hour < 6)
        up = ctx.tilt_deg >= 30.0            # Tier 2: the head is pointed UP
        if reading.scene == "sky":
            # PIXELS ALONE OFFER; PIXELS PLUS POSTURE FIRE.
            #
            # Rain on a dark window is many tiny bright points scattered over the
            # whole frame — which is also the definition of a starfield, and there
            # is no count, size or spread that separates them. Measured on noisy
            # JPEG frames: droplets give 597 lights of mean length 2.0 across 99% of
            # the frame; a real starfield gives 91 of length 1.0 across 97%. Firing
            # an astronomy lens at 0.8 on that was a guess wearing a decimal point.
            #
            # So the frame earns a place in the chooser (0.55, a hair over identify's
            # 0.45 but inside the 0.2 gap, so the wearer is asked). Only when the
            # CAMERA IS ALSO POINTED UP, at night, is it unambiguous enough to run
            # without asking — because nobody photographs their window at 45 degrees
            # of elevation.
            if up and night:
                return LensBid(self.lens, self.label, 0.9, "sky",
                               reason="you looked up at the night sky")
            return LensBid(self.lens, self.label, 0.55, "sky",
                           reason="this could be the night sky")
        # Looking up at night at a DARK frame. Posture alone is not enough: with
        # only "up + night + not much text" this bid claimed a dark ceiling, a
        # blank wall and a keyboard, and because it was then the ONLY bidder the
        # arbiter fired it outright (a single bid is an automatic fire) — so the
        # wearer got "install the Stargazer pack" instead of the object label, and
        # the object floor never ran. It now requires the frame to actually be dark
        # and bids 0.3: enough to earn a place in the chooser, never enough to
        # outrank identify (0.75) on its own.
        if up and night and reading.sig("dark") \
                and (reading.sig("text_density", 0.0) or 0.0) < 0.12:
            return LensBid(self.lens, self.label, 0.3, "sky",
                           reason="you looked up into the dark")
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
