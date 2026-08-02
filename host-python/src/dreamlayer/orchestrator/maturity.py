"""orchestrator/maturity.py — the cold-start arc: OBSERVER → APPRENTICE → RESIDENT.

An anticipation engine with no baseline is a nag machine, and the first
hour decides whether the wearer trusts proactive cards forever. Until the
system has genuinely learned this person, it earns the right to interrupt
in stages:

  OBSERVER    from pairing until 48 h AND >=200 scored events.
              Zero proactive output. Explicit asks answered; Veil/safety
              cards always allowed. The system watches and learns
              (glance priors, place anchors, speaker baselines).
  APPRENTICE  until 7 days AND trailing-50 card dismissal < 40%.
              Proactive cards gated hard: confidence >= 0.85, kinds
              {commitment, event} only, max 3/day. No audible harks.
  RESIDENT    full kinds, thresholds owned by adaptive_confidence,
              attention harks enabled.

Regression: if the trailing-20 dismissal rate crosses 60%, drop one state
for 24 h ("Juno is recalibrating") — interrupting less is how trust is
repaired. State persists in the settings table so a restart never resets
the arc.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque

log = logging.getLogger("dreamlayer.maturity")


def _above_confidence(rows, min_confidence: float = 0.85):
    """The gate's own rule, in the shape a tuner can score: admit a card whose
    confidence clears the bar. Module-level because `FunctionClassifier`
    requires a picklable callable — no lambdas."""
    return [float(r.get("confidence", 0.0)) >= min_confidence for r in rows]

OBSERVER = "observer"
APPRENTICE = "apprentice"
RESIDENT = "resident"

OBSERVER_MIN_S = 48 * 3600.0
OBSERVER_MIN_EVENTS = 200
APPRENTICE_MIN_S = 7 * 86400.0
APPRENTICE_WINDOW = 50
APPRENTICE_MAX_DISMISS = 0.40
# RESIDENT (audible harks) must be EARNED on evidence, not just time. With an
# empty card history _dismiss_rate() is 0.0, which cleared the dismissal gate
# vacuously — a wearer who never engaged (or was never shown) a card got
# promoted to audible interruptions. Require a minimum of resolved cards first.
RESIDENT_MIN_CARDS = 10
APPRENTICE_MIN_CONFIDENCE = 0.85
APPRENTICE_DAILY_CAP = 3
APPRENTICE_KINDS = frozenset({"commitment", "event"})
REGRESS_WINDOW = 20
REGRESS_DISMISS = 0.60
REGRESS_HOLD_S = 24 * 3600.0

# --- the learned half of APPRENTICE_MIN_CONFIDENCE --------------------------
#
# 0.85 is a hand-picked guess, and it is the same guess for everyone. The
# wearer meanwhile labels this exact question all day: a proactive card arrives
# carrying a confidence, and they keep it or swat it. `tuned_confidence()`
# fits the SAME readable rule — "interrupt above X" — to that history
# (orchestrator/persona_humanlearn.tune, the `persona_tuning` capability).
#
# It can only ever RAISE the bar. A learned threshold below the hand-picked
# floor would let the system talk its way into interrupting more using the
# wearer's own annoyance as the argument, and a trust mechanism that can
# loosen itself from its own output is not a trust mechanism. Tightening is
# safe in a way loosening is not, so only tightening is possible.
CONFIDENCE_GRID = (0.85, 0.88, 0.90, 0.92, 0.95, 0.97)
#: Labelled cards before the fit is consulted at all. Above
#: `persona_humanlearn.MIN_EXAMPLES` on purpose: this one gates INTERRUPTIONS.
TUNE_MIN_CARDS = 20

_SETTINGS_KEY = "maturity"


class MaturityGate:
    """Consulted by every proactive surface (anticipate_tick, on_place,
    attention_tick). db is optional — with one, state persists across
    restarts via the settings table."""

    def __init__(self, db=None, now_fn=None) -> None:
        self.db = db
        self._now = now_fn or time.time
        self.paired_at = self._now()
        self.events_seen = 0
        self._cards: deque[bool] = deque(maxlen=APPRENTICE_WINDOW)   # True = dismissed
        # (features, dismissed) for the cards whose confidence we were told.
        # Parallel to `_cards` rather than replacing it: every existing gate
        # reads that deque, and a saved profile written before this existed
        # must keep working untouched.
        self._labelled: deque = deque(maxlen=APPRENTICE_WINDOW)
        self._tuned_confidence: float = 0.0
        self.regressed_until = 0.0
        self._resident = False        # RESIDENT is sticky once earned
        self._sent_today = 0
        self._sent_day = self._day()
        self._load()

    # -- inputs ------------------------------------------------------------

    def observe_event(self, n: int = 1) -> None:
        """A scored ring/ingest event landed — the OBSERVER exit counter."""
        self.events_seen += n
        if self.events_seen % 25 == 0:
            self._save()

    def observe_card(self, dismissed: bool, now: float | None = None,
                     confidence: float | None = None, kind: str = "") -> None:
        """A proactive card was resolved (telemetry CARD_DISMISSED method
        'tap'/'expire' → dismissed=True when the wearer swatted it).

        `confidence`/`kind` are optional and additive: a caller that does not
        supply them behaves exactly as before, and the labelled log simply
        stays empty, which `tuned_confidence()` reports as "not enough".
        """
        now = self._now() if now is None else now
        self._cards.append(bool(dismissed))
        if confidence is not None:
            try:
                self._labelled.append(
                    ({"confidence": max(0.0, min(1.0, float(confidence))),
                      "kind": str(kind or "")}, bool(dismissed)))
                self._tuned_confidence = 0.0      # the fit is stale now
            except (TypeError, ValueError):
                pass                             # a bad number is not a label
        recent = list(self._cards)[-REGRESS_WINDOW:]
        if len(recent) >= REGRESS_WINDOW and \
                sum(recent) / len(recent) > REGRESS_DISMISS:
            self.regressed_until = now + REGRESS_HOLD_S
        self._save()

    # -- state -------------------------------------------------------------

    def state(self, now: float | None = None) -> str:
        now = self._now() if now is None else now
        age = now - self.paired_at
        earned = OBSERVER
        if age >= OBSERVER_MIN_S and self.events_seen >= OBSERVER_MIN_EVENTS:
            earned = APPRENTICE
        # RESIDENT promotion is sticky: earned once (time served + low
        # dismissals), it doesn't flicker with every window — a later bad
        # streak expresses itself through REGRESSION, not double-demotion.
        if earned == APPRENTICE and not self._resident \
                and age >= APPRENTICE_MIN_S \
                and len(self._cards) >= RESIDENT_MIN_CARDS \
                and self._dismiss_rate() < APPRENTICE_MAX_DISMISS:
            self._resident = True
            self._save()
        if earned == APPRENTICE and self._resident:
            earned = RESIDENT
        if now < self.regressed_until:
            earned = {RESIDENT: APPRENTICE,
                      APPRENTICE: OBSERVER}.get(earned, OBSERVER)
        return earned

    def recalibrating(self, now: float | None = None) -> bool:
        return (self._now() if now is None else now) < self.regressed_until

    # -- the gates ---------------------------------------------------------

    def allows_proactive(self, kind: str = "", confidence: float = 1.0,
                         now: float | None = None) -> bool:
        """May a proactive card surface right now? Counts what it admits
        (the APPRENTICE daily cap is enforced here)."""
        now = self._now() if now is None else now
        st = self.state(now)
        if st == OBSERVER:
            return False
        if st == APPRENTICE:
            if kind and kind not in APPRENTICE_KINDS:
                return False
            if confidence < (self.tuned_confidence()
                             or APPRENTICE_MIN_CONFIDENCE):
                return False
            if self._sent_count(now) >= APPRENTICE_DAILY_CAP:
                return False
            self._mark_sent(now)
        return True

    def tuned_confidence(self) -> float:
        """The confidence bar this wearer's own dismissals argue for, or 0.0.

        Fitted to the SAME rule the gate applies — "interrupt above X" — so the
        answer stays something you can say out loud. Clamped to
        APPRENTICE_MIN_CONFIDENCE from below: see CONFIDENCE_GRID for why only
        tightening is on offer.

        Cached until the next labelled card, because a grid search per card is
        work the interrupt path should not pay for.
        """
        if self._tuned_confidence:
            return self._tuned_confidence
        if len(self._labelled) < TUNE_MIN_CARDS:
            return 0.0
        try:
            from .persona_humanlearn import tune
            rows = [f for f, _d in self._labelled]
            # KEPT is the positive class: the bar should admit what the wearer
            # welcomed. Labelling by dismissal would fit the rule to what they
            # swatted and then admit exactly that.
            labels = [not d for _f, d in self._labelled]
            best = tune(_above_confidence, rows, labels,
                        {"min_confidence": list(CONFIDENCE_GRID)})
        except Exception as exc:                     # noqa: BLE001
            log.debug("[maturity] confidence tuning failed: %s",
                      type(exc).__name__)
            return 0.0
        if not best:
            return 0.0
        self._tuned_confidence = max(APPRENTICE_MIN_CONFIDENCE,
                                     float(best.params.get("min_confidence",
                                                           0.0)))
        return self._tuned_confidence

    def allows_hark(self, now: float | None = None) -> bool:
        """Audible interruptions are RESIDENT-only — the last privilege
        the system earns."""
        return self.state(now) == RESIDENT

    def summary(self, now: float | None = None) -> dict:
        now = self._now() if now is None else now
        return {
            "state": self.state(now),
            "recalibrating": self.recalibrating(now),
            "events_seen": self.events_seen,
            "dismiss_rate": round(self._dismiss_rate(), 3),
            "confidence_bar": round(self.tuned_confidence()
                                    or APPRENTICE_MIN_CONFIDENCE, 3),
            "labelled_cards": len(self._labelled),
            "age_hours": round((now - self.paired_at) / 3600.0, 1),
        }

    # -- internals -----------------------------------------------------------

    def _dismiss_rate(self) -> float:
        if not self._cards:
            return 0.0
        return sum(self._cards) / len(self._cards)

    def _day(self, now: float | None = None) -> int:
        return int((self._now() if now is None else now) // 86400)

    def _sent_count(self, now: float) -> int:
        if self._day(now) != self._sent_day:
            self._sent_day, self._sent_today = self._day(now), 0
        return self._sent_today

    def _mark_sent(self, now: float) -> None:
        self._sent_count(now)
        self._sent_today += 1
        self._save()

    def _load(self) -> None:
        if self.db is None:
            return
        try:
            raw = self.db.get_setting(_SETTINGS_KEY)
            if not raw:
                self._save()      # first boot: pin paired_at durably
                return
            d = json.loads(raw)
            self.paired_at = float(d.get("paired_at", self.paired_at))
            self.events_seen = int(d.get("events_seen", 0))
            self.regressed_until = float(d.get("regressed_until", 0.0))
            self._resident = bool(d.get("resident", False))
            self._sent_today = int(d.get("sent_today", 0))
            self._sent_day = int(d.get("sent_day", self._sent_day))
            for dismissed in d.get("cards", []):
                self._cards.append(bool(dismissed))
            # A profile written before the labelled log existed simply has no
            # "labelled" key, and the fit stays unavailable until the wearer
            # resolves TUNE_MIN_CARDS more — which is the honest state, not a
            # regression.
            for row in d.get("labelled", []):
                try:
                    self._labelled.append(({
                        "confidence": float(row["confidence"]),
                        "kind": str(row.get("kind", ""))}, bool(row["d"])))
                except (TypeError, ValueError, KeyError):
                    continue      # one bad row must not drop the rest
        except Exception:
            pass                  # a corrupt blob never blocks boot

    def _save(self) -> None:
        if self.db is None:
            return
        try:
            self.db.set_setting(_SETTINGS_KEY, json.dumps({
                "paired_at": self.paired_at,
                "events_seen": self.events_seen,
                "regressed_until": self.regressed_until,
                "resident": self._resident,
                "sent_today": self._sent_today,
                "sent_day": self._sent_day,
                "cards": [bool(x) for x in self._cards],
                "labelled": [{"confidence": f["confidence"],
                              "kind": f.get("kind", ""), "d": bool(dis)}
                             for f, dis in self._labelled],
            }))
        except Exception:
            pass


class ResidentGate:
    """Permissive stand-in with the same surface. Ephemeral (:memory:)
    sessions — demos, tests, the simulator — skip the cold-start arc;
    every real install (persistent DB) earns it through MaturityGate."""

    def observe_event(self, n: int = 1) -> None: ...

    def observe_card(self, dismissed: bool, now=None,
                     confidence=None, kind: str = "") -> None: ...

    def tuned_confidence(self) -> float:
        return 0.0

    def state(self, now=None) -> str:
        return RESIDENT

    def recalibrating(self, now=None) -> bool:
        return False

    def allows_proactive(self, kind: str = "", confidence: float = 1.0,
                         now=None) -> bool:
        return True

    def allows_hark(self, now=None) -> bool:
        return True

    def summary(self, now=None) -> dict:
        return {"state": RESIDENT, "recalibrating": False,
                "events_seen": 0, "dismiss_rate": 0.0, "age_hours": 0.0}
