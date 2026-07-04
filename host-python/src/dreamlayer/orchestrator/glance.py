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
          "screen", "shelf", "menu", "unknown")


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


@dataclass
class LensBid:
    """A candidate lens's bid to own this glance."""
    lens: str                        # stable key: "scholar_answer", "oracle"…
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


class OracleCandidate(LensCandidate):
    lens, label = "oracle", "Identify"

    def bid(self, reading, ctx):
        if reading.scene == "object":
            return LensBid(self.lens, self.label, 0.75, "oracle",
                           reason="an object is in view")
        if reading.scene in ("text", "screen") and not _q(reading):
            # a weak default so a bare look at text still has a fallback owner
            return LensBid(self.lens, self.label, 0.32, "oracle",
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
        items = reading.sig("items", 0) or 0
        if reading.scene in ("shelf", "menu") or items >= 2:
            s = 0.88 if reading.scene in ("shelf", "menu") else 0.6
            return LensBid(self.lens, self.label, s, "taste",
                           reason=f"{items} items to compare" if items else "a shelf/menu")
        return None


DEFAULT_CANDIDATES = [
    PersonCandidate(), TasteLensCandidate(), ScholarFormCandidate(),
    ScholarAnswerCandidate(), RosettaCandidate(), ScholarExplainCandidate(),
    OracleCandidate(),
]

# spoken lens hints → the lens key they favour
INTENT_LENS = {
    "answer": "scholar_answer", "form": "scholar_form",
    "explain": "scholar_explain", "translate": "rosetta",
    "object": "oracle", "person": "person", "compare": "taste",
}


# --- learned per-scene priors ("it learns you") ------------------------------

class GlancePriors:
    """A tiny online preference model: for each scene kind, how often you've
    chosen each lens. Reinforced when you pick from a chooser (or don't dismiss
    a fired lens).

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

    def reinforce(self, scene: str, lens: str, amount: float = 1.0) -> None:
        self._c.setdefault(scene, {})
        self._c[scene][lens] = self._c[scene].get(lens, 0.0) + amount
        self._save()

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
        return max(row, key=row.get) if row else None

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
        if reading.confidence and reading.confidence < 0.5:
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
        for cand in self.candidates:
            b = cand.bid(reading, ctx)
            if b is None:
                continue
            # learned prior nudge for this scene
            pboost = self.priors.boost(reading.scene, b.lens)
            if pboost:
                b = b.boosted(pboost, "you often pick this here")
            # a matching spoken intent is a strong, deliberate steer
            if ctx.recent_intent and INTENT_LENS.get(ctx.recent_intent) == b.lens:
                b = b.boosted(0.4, f"you asked to {ctx.recent_intent}")
            # a long dwell reads as stronger intent overall
            if ctx.dwell_ms >= 700:
                b = b.boosted(0.05, "held gaze")
            bids.append(b)

        if not bids:
            return self._remember(reading, GlanceDecision("none", reading))
        bids.sort(key=lambda x: x.salience, reverse=True)
        top = bids[0]
        if top.salience < self.floor:
            return self._remember(reading, GlanceDecision("none", reading))

        runner = bids[1].salience if len(bids) > 1 else 0.0
        forced = bool(ctx.recent_intent and INTENT_LENS.get(ctx.recent_intent) == top.lens)

        # hysteresis: if we just decided this same scene→winner, keep it steady
        held = self._held(reading.scene, top.lens)
        if held is not None:
            return held

        if forced or (top.salience - runner) >= self.gap or len(bids) == 1:
            return self._remember(reading, GlanceDecision("fire", reading, winner=top))

        options = [b for b in bids if (top.salience - b.salience) < self.gap][:3]
        card = _choice_card(reading, options)
        return self._remember(reading, GlanceDecision("offer", reading,
                                                      options=options, card=card))

    def reinforce(self, scene: str, lens: str) -> None:
        """Teach the arbiter which lens you chose for this kind of scene."""
        self.priors.reinforce(scene, lens)

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

    items = int(s.get("items", 0) or 0)
    if has_face and density < 0.3:
        return GlanceReading("person", 0.7, s)
    if s.get("menu"):
        return GlanceReading("menu", 0.65, s)
    if s.get("shelf") or items >= 2:
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
    if s.get("object") or s.get("has_object"):
        return GlanceReading("object", 0.55, s)
    return GlanceReading("unknown", 0.2, s)


def _choice_card(reading: GlanceReading, options: list) -> dict:
    from ..hud import cards
    return cards.glance_choice([{"label": o.label, "lens": o.lens,
                                 "action": o.action, "args": o.args}
                                for o in options], scene=reading.scene)
