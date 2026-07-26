"""orchestrator/glance.py — the Glance Arbiter: what am I looking at, and which
lens should own it?

DreamLayer has no mode picker on purpose — a menu is friction on glasses. But
that leaves one gap: on a *look*, several lenses could apply (is that page a
form to fill, a question to answer, foreign text to translate, or an object to
name?). The Glance Arbiter closes it. Given a reading of what's in view and a
little context, each candidate lens *bids*; the arbiter fires the clear winner,
offers a one-tap chooser when it's genuinely ambiguous, and does nothing when
nothing fits. The wearer never picks a mode — the look decides.

The shape is deliberately the Object Lens provider-registry pattern, lifted up
a level: there, providers declare `matches(sighting)` and the registry merges
their rows into one panel; here, lens candidates declare `bid(reading, ctx)`
and the registry ranks them into one decision. Same idea — declarative
candidates, a registry that composes — reused for arbitration instead of panel
assembly.

Design tenets:

  seam-injected   The scene classifier is a seam (`classify_fn`), so the fast
                  on-device read and the Mac's Ollama vision read plug into the
                  same hole. A pure coarse heuristic (`classify_coarse`) means
                  the arbiter works today with zero model, from cheap signals.

  two-tier        `is_ambiguous(reading)` lets the hub spend the big model only
                  when the cheap read can't tell a form from a question — the
                  arbiter decides *when* fine vision is worth the latency.

  it learns you   Per-scene priors (`GlancePriors`) reinforce the lens you keep
                  choosing for a kind of scene, so tomorrow's ambiguous glance
                  leans your way. Serialisable, so the Mac Brain can persist it.

  calm            Hysteresis holds a fresh decision for a debounce window, so a
                  glance that flickers across a page doesn't flip lenses.

  inspectable     Every bid carries a `reason`; the decision is pure and
                  testable, no hidden global state.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Optional


# --- the vocabulary of a glance ---------------------------------------------

# scene kinds the classifier may return. Kept small and concrete.
SCENES = ("object", "text", "form", "question", "foreign_text", "person",
          "screen", "shelf", "menu", "sky", "unknown")
# Tier 4: priors are learned PER TIME OF DAY as well as per scene — the lens you
# want from a page of text at 8am (brief/read) is not the one you want at 11pm.
# A fixed vocabulary, so the on-disk priors stay bounded to |SCENES|×|DAYPARTS|.
DAYPARTS = ("morning", "afternoon", "evening", "night")


def daypart(hour: int) -> str:
    h = int(hour) % 24
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


@dataclass
class GlanceReading:
    """What the classifier saw in the frame. `signals` carry the cheap cues a
    coarse on-device read can produce; `scene` is the resolved kind."""
    scene: str = "unknown"
    confidence: float = 0.0
    signals: dict = field(default_factory=dict)   # text_density, has_face,
                                                  # question, form_fields,
                                                  # language, handwriting…

    def sig(self, key, default=None):
        return self.signals.get(key, default)


@dataclass
class GlanceContext:
    """The context the arbiter weighs alongside the reading."""
    recent_intent: str = ""          # a spoken lens hint within the last beat
    user_language: str = "en"
    dwell_ms: float = 0.0            # gaze dwell — longer = stronger intent
    focus: bool = False
    veiled: bool = False
    # Tier 2: where the head is pointed and when it is. Tilt is degrees, + is UP
    # (looking at the sky), - is DOWN (looking at a page in your hands); hour is
    # the wearer's LOCAL hour. Both are cheap, on-device, and never leave.
    tilt_deg: float = 0.0
    hour: int = -1

    def __post_init__(self):
        # This is a shared dataclass at a public seam and `hour` is compared with
        # `>=` inside arbitrate(), so a caller passing a string ("8" from a query
        # param, say) raised a TypeError from the middle of arbitration. Coerce
        # once here; anything uninterpretable becomes "unknown", which every
        # consumer already treats as "don't infer from the clock".
        try:
            self.hour = int(self.hour)
        except (TypeError, ValueError):
            self.hour = -1
        try:
            self.tilt_deg = float(self.tilt_deg)
        except (TypeError, ValueError):
            self.tilt_deg = 0.0


@dataclass
class LensBid:
    """A candidate lens's bid to own this glance."""
    lens: str                        # stable key: "scholar_answer", "juno"…
    label: str                       # human, for the chooser ("Answer this")
    salience: float                  # 0–1, how strongly it applies
    action: str                      # action key the hub maps to a method
    args: dict = field(default_factory=dict)
    reason: str = ""

    def boosted(self, delta: float, why: str = "") -> "LensBid":
        s = max(0.0, min(1.0, self.salience + delta))
        r = self.reason + (f"; {why}" if why else "")
        return LensBid(self.lens, self.label, s, self.action, dict(self.args), r)


@dataclass
class GlanceDecision:
    kind: str                        # "fire" | "offer" | "none"
    reading: GlanceReading
    winner: Optional[LensBid] = None
    options: list = field(default_factory=list)   # for "offer"
    card: Optional[dict] = None      # the chooser card, when offering


# --- candidates: each lens decides whether (and how strongly) it applies -----

class LensCandidate:
    """Base class. A candidate inspects a reading + context and returns a bid,
    or None when it doesn't apply — the arbitration analogue of a provider's
    `matches()`."""
    lens = "candidate"
    label = "Lens"

    def bid(self, reading: GlanceReading, ctx: GlanceContext) -> Optional[LensBid]:
        raise NotImplementedError


def _q(reading):  # is there a question in view?
    return bool(reading.sig("question")) or reading.scene == "question"


class ScholarAnswerCandidate(LensCandidate):
    lens, label = "scholar_answer", "Answer it"

    def bid(self, reading, ctx):
        if reading.scene == "question" or (reading.scene in ("text", "screen") and _q(reading)):
            s = 0.9 if reading.scene == "question" else 0.62
            return LensBid(self.lens, self.label, s, "scholar_answer",
                           reason="a question is in view")
        return None


class ScholarFormCandidate(LensCandidate):
    lens, label = "scholar_form", "Fill it in"

    def bid(self, reading, ctx):
        fields = reading.sig("form_fields", 0) or 0
        if reading.scene == "form" or fields >= 2:
            s = 0.9 if reading.scene == "form" else 0.6
            return LensBid(self.lens, self.label, s, "scholar_form",
                           reason=f"{fields} fillable fields" if fields else "a form is in view")
        return None


class ScholarExplainCandidate(LensCandidate):
    lens, label = "scholar_explain", "Plain words"

    def bid(self, reading, ctx):
        dense = (reading.sig("text_density", 0.0) or 0.0) >= 0.5
        if reading.scene == "text" and dense and not _q(reading):
            legal = bool(reading.sig("legal") or reading.sig("technical"))
            return LensBid(self.lens, self.label, 0.7 if legal else 0.5,
                           "scholar_explain",
                           reason="dense" + (" legal/technical" if legal else "") + " text")
        return None


class RosettaCandidate(LensCandidate):
    lens, label = "rosetta", "Translate"

    def bid(self, reading, ctx):
        lang = (reading.sig("language") or "").lower()
        foreign = reading.scene == "foreign_text" or (lang and lang != (ctx.user_language or "en").lower())
        if foreign and reading.scene in ("text", "foreign_text", "screen"):
            return LensBid(self.lens, self.label, 0.85, "translate",
                           args={"language": lang},
                           reason=f"text in {lang or 'another language'}")
        return None


class JunoCandidate(LensCandidate):
    lens, label = "juno", "Identify"

    def bid(self, reading, ctx):
        if reading.scene == "object":
            return LensBid(self.lens, self.label, 0.75, "juno",
                           reason="an object is in view")
        # `sky` was added to SCENES for the live path, which has a SkyCandidate.
        # The default (glasses) candidate set has none — so the new scene made a
        # dark frame resolve to something NOTHING could bid on, and a look that
        # used to identify what was in front of you started doing nothing at all.
        # Identify owns it here: naming what's in view is always a valid answer,
        # and a set that grows a scene must never lose an owner for it.
        if reading.scene == "sky":
            return LensBid(self.lens, self.label, 0.45, "juno",
                           reason="name what's above you")
        # Identify is the fallback owner for scenes whose specialist lens this
        # candidate set cannot run. On the LIVE (phone) set there is no form or
        # question lens, so a photographed form used to resolve to `form` and then
        # find nobody willing to bid — the look simply did nothing. Naming what is
        # in view is always a valid answer; silence never is.
        if reading.scene in ("form", "question"):
            return LensBid(self.lens, self.label, 0.4, "juno",
                           reason="fallback: name what's here")
        if reading.scene in ("text", "screen") and not _q(reading):
            # a weak default so a bare look at text still has a fallback owner
            return LensBid(self.lens, self.label, 0.32, "juno",
                           reason="fallback: name what's here")
        return None


class PersonCandidate(LensCandidate):
    lens, label = "person", "Who is this"

    def bid(self, reading, ctx):
        if reading.scene == "person" or reading.sig("has_face"):
            return LensBid(self.lens, self.label, 0.95, "person",
                           reason="a face is in view")
        return None


class TasteLensCandidate(LensCandidate):
    lens, label = "taste", "Compare"

    def bid(self, reading, ctx):
        # Only a real shelf/menu. There used to be an `items >= 2` fallback that
        # bid on any two detections at all, which is how a desk became something to
        # comparison-shop. Several DIFFERENT things is clutter, and clutter is
        # SegmentCandidate's business, not this lens's.
        if reading.scene not in ("shelf", "menu"):
            return None
        items = reading.sig("items", 0) or 0
        return LensBid(self.lens, self.label, 0.88, "taste",
                       reason=f"{items} items to compare" if items else "a shelf/menu")


DEFAULT_CANDIDATES = [
    PersonCandidate(), TasteLensCandidate(), ScholarFormCandidate(),
    ScholarAnswerCandidate(), RosettaCandidate(), ScholarExplainCandidate(),
    JunoCandidate(),
]

# spoken lens hints → the lens key they favour
INTENT_LENS = {
    "answer": "scholar_answer", "form": "scholar_form",
    "explain": "scholar_explain", "translate": "rosetta",
    "object": "juno", "person": "person", "compare": "taste",
    # Tier 3 — what you SAY is not a guess about your intent, it IS your intent
    "read": "read", "math": "math", "find": "find", "depth": "depth",
    "sky": "sky", "segment": "segment",
}


# --- learned per-scene priors ("it learns you") ------------------------------

MAX_PRIOR_LENSES = 12       # distinct lens keys one scene row may ever hold
PRIOR_DECAY = 0.9           # each new pick fades the older ones by this much


class GlancePriors:
    """A tiny online preference model: for each scene kind, how often you've
    chosen each lens. Reinforced when you pick from a chooser.

    Counts DECAY as they accumulate (`PRIOR_DECAY`), which does two things. It
    bounds every row — the total converges on 1/(1-decay) = 10 instead of growing
    forever — and, more importantly, it makes a habit revisable: four contrary
    picks pull a fully-formed preference back below the confidence share, where
    unbounded counters would have needed hundreds.

    Persisted as a small JSON on the hub, beside the vault, exactly like the
    UserModel: read once at start, rewritten (atomically) on each reinforce, and
    purely in-memory when no `path` is given. Serialisable either way, so the
    Mac Brain can later mirror it across hubs — but the local file is the source
    of truth on the hot path, so a glance never waits on the network."""

    def __init__(self, counts: Optional[dict] = None, weight: float = 0.12,
                 path: Optional[str] = None):
        self._c: dict[str, dict[str, float]] = counts or {}
        self.weight = float(weight)          # max salience nudge from a strong prior
        self.path = path
        self._load()

    @staticmethod
    def _key(scene: str, part: str = "") -> str:
        """scene, or scene@daypart — both drawn from fixed vocabularies so a
        crafted value can never grow the file (it is rewritten whole)."""
        if part and part in DAYPARTS:
            return f"{scene}@{part}"
        return scene

    def reinforce_at(self, scene: str, lens: str, part: str = "",
                     amount: float = 1.0) -> None:
        """Learn the pick for this scene AND for this scene-at-this-time-of-day,
        so the arbiter can grow a habit that is specific to your mornings without
        forgetting the general one."""
        self.reinforce(scene, lens, amount)
        if part and part in DAYPARTS and scene in SCENES:
            self._bump(self._key(scene, part), lens, amount)
            self._save()

    def boost_at(self, scene: str, lens: str, part: str = "") -> float:
        """The stronger of the general and the time-of-day prior."""
        b = self.boost(scene, lens)
        if part and part in DAYPARTS:
            # This was `self.boost(key) if False else self._boost_key(key, lens)`.
            # The dead operand called the two-argument `boost` with one argument, so
            # anything that simplified the constant condition — a refactor, a
            # linter — would have made every arbitrate() raise a TypeError, which
            # world_lens.glance swallows into "kind: object": the whole automatic
            # lens silently gone. Removed rather than left as a tripwire.
            b = max(b, self._boost_key(self._key(scene, part), lens))
        return b

    def _boost_key(self, key: str, lens: str) -> float:
        row = self._c.get(key)
        if not row:
            return 0.0
        total = sum(row.values())
        if total <= 0:
            return 0.0
        return self.weight * (row.get(lens, 0.0) / total)

    def confident(self, scene: str, lens: str, part: str = "",
                  share: float = 0.7, floor: float = 3.0) -> bool:
        """True when you have picked `lens` for this scene enough times, and
        dominantly enough, that asking again would be pestering you."""
        for key in ([self._key(scene, part)] if part else []) + [scene]:
            row = self._c.get(key) or {}
            total = sum(row.values())
            if total >= floor and (row.get(lens, 0.0) / total) >= share:
                return True
        return False

    def reinforce(self, scene: str, lens: str, amount: float = 1.0) -> None:
        # Only the fixed vocabulary of scenes may become a key — an unknown
        # (crafted/oversized) scene must never grow this file, which is rewritten
        # whole on every reinforce. Bounds the on-disk priors to |SCENES| keys.
        if scene not in SCENES:
            return
        self._bump(scene, lens, amount)
        self._save()

    def _bump(self, key: str, lens: str, amount: float) -> None:
        """Decay the row, then credit `lens`. The LENS side is bounded here too:
        `scene` was validated against SCENES but `lens` was taken verbatim, so a
        crafted 100 000-character lens name grew this file — which is rewritten
        whole on every pick — to 107 KB, and 500 distinct names to 115 KB. A lens
        key is a short identifier or it is not a lens key."""
        lens = str(lens or "")[:48]
        if not lens:
            return
        row = self._c.setdefault(key, {})
        if lens not in row and len(row) >= MAX_PRIOR_LENSES:
            return
        for k in list(row):
            row[k] = round(row[k] * PRIOR_DECAY, 6)
            if row[k] < 1e-3:
                del row[k]
        row[lens] = round(row.get(lens, 0.0) + amount, 6)

    def boost(self, scene: str, lens: str) -> float:
        """Salience nudge in [0, weight] for `lens` given past picks for `scene`."""
        row = self._c.get(scene)
        if not row:
            return 0.0
        total = sum(row.values())
        if total <= 0:
            return 0.0
        return self.weight * (row.get(lens, 0.0) / total)

    def favourite(self, scene: str) -> Optional[str]:
        row = self._c.get(scene)
        return max(row, key=lambda k: row[k]) if row else None

    def to_dict(self) -> dict:
        return {"counts": self._c, "weight": self.weight}

    @classmethod
    def from_dict(cls, d: dict) -> "GlancePriors":
        d = d or {}
        return cls(counts=d.get("counts") or {}, weight=d.get("weight", 0.12))

    # -- persistence (mirrors UserModel: atomic write, silent on failure) --

    def _save(self) -> None:
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.to_dict(), f)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                d = json.load(f)
            self._c = {str(scene): {str(lens): float(v) for lens, v in (row or {}).items()}
                       for scene, row in (d.get("counts") or {}).items()}
            self.weight = float(d.get("weight", self.weight))
        except Exception:
            pass


# --- the arbiter -------------------------------------------------------------

class GlanceArbiter:
    """Ranks candidate lens bids into one decision: fire / offer / none.

    Parameters
    ----------
    candidates : list[LensCandidate]
        The lenses that may bid. Defaults to the built-ins.
    priors : GlancePriors
        Learned per-scene preference; nudges close calls your way.
    priors_path : str
        When `priors` isn't supplied, load/persist the learned priors here (a
        small JSON beside the vault). None ⇒ in-memory only.
    floor : float
        A top bid below this yields no action (nothing is worth surfacing).
    gap : float
        Fire outright when the top bid beats the runner-up by at least this;
        otherwise offer a chooser of the close contenders.
    debounce_ms : float
        Hold a fresh decision for this long so a wandering glance doesn't flip
        lenses (hysteresis).
    now_fn : callable
        Injectable clock for deterministic tests.
    """

    def __init__(self, candidates=None, priors: Optional[GlancePriors] = None,
                 floor: float = 0.35, gap: float = 0.2, debounce_ms: float = 1200.0,
                 now_fn: Optional[Callable[[], float]] = None,
                 priors_path: Optional[str] = None):
        self.candidates = list(candidates if candidates is not None else DEFAULT_CANDIDATES)
        self.priors = priors or GlancePriors(path=priors_path)
        self.floor = float(floor)
        self.gap = float(gap)
        self.debounce_ms = float(debounce_ms)
        import time
        self._now = now_fn or (lambda: time.monotonic() * 1000.0)
        self._last: Optional[tuple] = None      # (scene, winner_lens, ts, decision)

    def is_ambiguous(self, reading: GlanceReading) -> bool:
        """True when a coarse read can't confidently name the scene — the hub's
        cue to escalate to fine (Mac/cloud) vision before arbitrating."""
        if reading.scene == "unknown":
            return True
        # A 0.0 (or unset) confidence is the MOST ambiguous read, not the least
        # — the old `reading.confidence and ...` short-circuited on falsy 0.0 and
        # declared it unambiguous, skipping the fine read exactly when it was
        # needed most. Treat missing/zero confidence as ambiguous.
        if (reading.confidence or 0.0) < 0.5:
            return True
        # dense text that might be a form OR a question OR prose is the classic
        # case worth a fine read.
        if reading.scene in ("text", "screen") and (reading.sig("text_density", 0.0) or 0.0) >= 0.4:
            return True
        return False

    def arbitrate(self, reading: GlanceReading,
                  ctx: Optional[GlanceContext] = None) -> GlanceDecision:
        ctx = ctx or GlanceContext()
        if ctx.veiled:
            return GlanceDecision("none", reading)

        bids: list[LensBid] = []
        raw: dict = {}                 # salience BEFORE the learned prior nudge
        for cand in self.candidates:
            b = cand.bid(reading, ctx)
            if b is None:
                continue
            raw[b.lens] = b.salience
            # learned prior nudge for this scene — and for this scene at this
            # time of day, which is the sharper signal (Tier 4)
            part = daypart(ctx.hour) if ctx.hour is not None and ctx.hour >= 0 else ""
            pboost = self.priors.boost_at(reading.scene, b.lens, part)
            if pboost:
                b = b.boosted(pboost, "you often pick this here")
            # a matching spoken intent is a strong, deliberate steer
            if ctx.recent_intent and INTENT_LENS.get(ctx.recent_intent) == b.lens:
                b = b.boosted(0.4, f"you asked to {ctx.recent_intent}")
            # A long dwell reads as stronger intent overall — but only for a
            # candidate that was already viable. A bid deliberately placed BELOW the
            # floor ("enough for a chooser, never enough to carry a look") was being
            # lifted over it by this generic +0.05: the posture-only sky bid of 0.30
            # became 0.35, and since the floor test is a strict `<` and it was the
            # only bidder, holding still for 700ms auto-ran an astronomy lens at a
            # dark ceiling. Dwell strengthens a real candidate; it does not create
            # one.
            if ctx.dwell_ms >= 700 and b.salience >= self.floor:
                b = b.boosted(0.05, "held gaze")
            bids.append(b)

        if not bids:
            return self._remember(reading, GlanceDecision("none", reading))
        bids.sort(key=lambda x: x.salience, reverse=True)
        top = bids[0]
        if top.salience < self.floor:
            return self._remember(reading, GlanceDecision("none", reading))

        runner = bids[1].salience if len(bids) > 1 else 0.0
        spoken = bool(ctx.recent_intent and INTENT_LENS.get(ctx.recent_intent) == top.lens)
        # Tier 4 — "it learns you" means it also stops ASKING you. Once you have
        # picked this lens for this scene dominantly and often enough, a close call
        # fires instead of offering a chooser you would answer the same way again.
        _part = daypart(ctx.hour) if ctx.hour is not None and ctx.hour >= 0 else ""
        learned = (not spoken) and self.priors.confident(reading.scene, top.lens, _part)
        forced = spoken or learned

        # hysteresis: if we just decided this same scene→winner, keep it steady
        held = self._held(reading.scene, top.lens)
        if held is not None:
            return held

        close = [b for b in bids if (top.salience - b.salience) < self.gap][:3]
        if forced or (top.salience - runner) >= self.gap or len(bids) == 1:
            # A fire the PRIORS forced still carries the alternatives it chose not
            # to ask about. Not asking is the point; making them UNREACHABLE was a
            # bug — on a scene it had learned, the chooser was the only route to the
            # other lens, so a habit (once even a mistaken one) locked that lens out
            # for good, on disk. Offering them without a dialog keeps both halves:
            # it fires straight away, and the other lens is still one tap off.
            #
            # The alternatives are judged on the UNBOOSTED bids: the habit's own
            # nudge is often what opened the gap, so measuring closeness after
            # applying it made the runner-up disappear exactly when the habit was
            # strongest. The question to ask is "would this have been a close call
            # without the habit?", which is what `raw` answers.
            alts = ([b for b in bids[1:]
                     if (raw.get(top.lens, top.salience)
                         - raw.get(b.lens, b.salience)) < self.gap][:2]
                    if learned else [])
            return self._remember(reading, GlanceDecision(
                "fire", reading, winner=top, options=alts))

        card = _choice_card(reading, close)
        return self._remember(reading, GlanceDecision("offer", reading,
                                                      options=close, card=card))

    def reinforce(self, scene: str, lens: str, hour: int = -1) -> None:
        """Teach the arbiter which lens you chose for this kind of scene — and, when
        the local `hour` is known, for this scene at this time of day.

        `hour` is what makes the daypart tier real. `reinforce_at` existed and was
        tested, but nothing in production ever called it: every teach path came
        through here and wrote the bare scene key, so `boost_at` and
        `confident(part=…)` were reading keys that could not exist. The two tests
        that claimed to cover it passed off the general key's fallback."""
        try:
            h = int(hour)
        except (TypeError, ValueError):
            h = -1
        self.priors.reinforce_at(scene, lens, daypart(h) if h >= 0 else "")

    # -- hysteresis bookkeeping ------------------------------------------

    def _held(self, scene, winner_lens):
        if not self._last:
            return None
        pscene, plens, pts, pdec = self._last
        if pscene == scene and plens == winner_lens and \
                (self._now() - pts) < self.debounce_ms:
            return pdec
        return None

    def _remember(self, reading, decision):
        w = decision.winner.lens if decision.winner else ""
        self._last = (reading.scene, w, self._now(), decision)
        return decision


# --- pure coarse classifier: a usable scene from cheap on-device signals -----

def classify_coarse(signals: dict, user_language: str = "en") -> GlanceReading:
    """Resolve a scene from cheap cues alone — no vision model. Whatever the
    device can produce (a face flag, a text-density estimate, a detected form
    grid, a question mark, a language guess) maps to a best-guess scene with a
    modest confidence, so the arbiter runs today and escalates when unsure."""
    s = dict(signals or {})
    has_face = bool(s.get("has_face"))
    density = float(s.get("text_density", 0.0) or 0.0)
    fields = int(s.get("form_fields", 0) or 0)
    question = bool(s.get("question"))
    lang = (s.get("language") or "").lower()
    foreign = bool(lang and lang != (user_language or "en").lower())

    if has_face and density < 0.3:
        return GlanceReading("person", 0.7, s)
    if s.get("menu"):
        return GlanceReading("menu", 0.65, s)
    # A shelf needs the SHELF cue, not merely a couple of detections. `items >= 2`
    # made a mug beside a laptop into "a shelf", which fired the compare lens at
    # 0.88 — above identify — on any desk. Two different objects are clutter; a
    # comparison needs several of the SAME kind of thing, which is what `shelf`
    # means (the phone seeing a repeated label).
    if s.get("shelf"):
        return GlanceReading("shelf", 0.65, s)
    if fields >= 2:
        return GlanceReading("form", 0.65, s)
    if question and density > 0.05:
        return GlanceReading("question", 0.6, s)
    if foreign and density > 0.1:
        return GlanceReading("foreign_text", 0.6, s)
    if density >= 0.5:
        return GlanceReading("text", 0.5, s)
    if density > 0.1:
        return GlanceReading("text", 0.4, s)
    # Looking UP at a dark field of point lights is the one scene where the intent
    # IS the sky — resolved after text so a lit sign never becomes it. No density
    # clause: the `density > 0.1` branch above already returned, so anything
    # reaching here is at most 0.1 and a `< 0.12` test could never fail.
    if s.get("sky"):
        return GlanceReading("sky", 0.6, s)
    if s.get("object") or s.get("has_object"):
        return GlanceReading("object", 0.55, s)
    return GlanceReading("unknown", 0.2, s)


def _choice_card(reading: GlanceReading, options: list) -> dict:
    from ..hud import cards
    return cards.glance_choice([{"label": o.label, "lens": o.lens,
                                 "action": o.action, "args": o.args}
                                for o in options], scene=reading.scene)
