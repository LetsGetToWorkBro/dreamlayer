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
import time
from collections import deque

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

    def observe_card(self, dismissed: bool, now: float | None = None) -> None:
        """A proactive card was resolved (telemetry CARD_DISMISSED method
        'tap'/'expire' → dismissed=True when the wearer swatted it)."""
        now = self._now() if now is None else now
        self._cards.append(bool(dismissed))
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
            if confidence < APPRENTICE_MIN_CONFIDENCE:
                return False
            if self._sent_count(now) >= APPRENTICE_DAILY_CAP:
                return False
            self._mark_sent(now)
        return True

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
            }))
        except Exception:
            pass


class ResidentGate:
    """Permissive stand-in with the same surface. Ephemeral (:memory:)
    sessions — demos, tests, the simulator — skip the cold-start arc;
    every real install (persistent DB) earns it through MaturityGate."""

    def observe_event(self, n: int = 1) -> None: ...

    def observe_card(self, dismissed: bool, now=None) -> None: ...

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
