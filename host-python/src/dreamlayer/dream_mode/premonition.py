"""dream_mode/premonition.py — the future side of the ring stops being empty.

The ring buffer knows your recurrences: Tuesdays at 18:00 you're at the
gym; after the gym you call your mother. The RecurrenceModel mines those
rhythms and renders *future ghosts* — faint shimmering marks ahead of the
now-notch showing what usually happens next. They harden into real marks
when the event actually lands (the prediction retires and the genuine
event takes its place), and they dissolve when defied: a slot that keeps
missing loses its voice and stops predicting.

This is Echo (the paradigm shelved in RC v2) reborn as weather instead
of proposals — no consent dialogs, no text, just probability made
faintly luminous. Precision over recall is the law here: the model
predicts only slots seen on at least MIN_DAYS distinct days, and its
one proving test is the two-Tuesdays test — a decoy that happened once
and a fortnight of noise must produce zero predictions.

Everything is local statistics over already-stored events; nothing new
is captured and nothing leaves the phone.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

MIN_DAYS = 2                 # a rhythm needs at least two distinct days
DAILY_WEEKDAYS = 4           # seen on ≥4 weekdays → predicts every day
LOOKAHEAD_H = 5.0            # the dial's future window
CONFIRM_TOL_S = 45 * 60.0    # a real event within ±45 min confirms
SUPPRESS_AFTER_MISSES = 2    # slots go quiet after repeated defiance
SUPPRESS_HIT_FACTOR = 0.4


def _slot_of(kind: str, summary: str, ts: float,
             place: Optional[str]) -> tuple:
    """A recurrence slot: what kind of thing, roughly where, weekday+hour.
    Summaries are reduced to a coarse shape (first content token) so
    'rolled with Dre' and 'rolling rounds' can share a rhythm without
    memorizing sentences."""
    tokens = [t for t in re.findall(r"[a-z]+", (summary or "").lower())
              if len(t) > 3]
    head = tokens[0] if tokens else kind
    tm = time.gmtime(ts)
    return (tm.tm_wday, tm.tm_hour, kind, head, place or "")


@dataclass
class Prediction:
    expected_ts: float
    kind: str
    slot: tuple
    confidence: float
    place: str

    @property
    def hour(self) -> int:
        return self.slot[1]


@dataclass
class _SlotStats:
    days: set = field(default_factory=set)
    weekdays: set = field(default_factory=set)
    hits: int = 0
    misses: int = 0

    def hit_factor(self) -> float:
        return (self.hits + 1) / (self.hits + self.misses + 1)

    def suppressed(self) -> bool:
        return self.misses >= SUPPRESS_AFTER_MISSES and \
            self.hit_factor() < SUPPRESS_HIT_FACTOR

    def confidence(self) -> float:
        return min(1.0, len(self.days) / 4.0) * self.hit_factor()


class RecurrenceModel:
    def __init__(self, now_fn=None) -> None:
        self._now = now_fn or time.time
        self._slots: dict[tuple, _SlotStats] = {}
        self._pending: dict[tuple, Prediction] = {}

    def clear(self) -> None:
        """Drop every learned recurrence slot + pending prediction — the
        recurrence model encodes place/time patterns, so erase-everything must
        forget it too (audit refute 2026-07)."""
        self._slots.clear()
        self._pending.clear()

    # -- learning ----------------------------------------------------------

    def observe(self, kind: str, summary: str, ts: float,
                place: Optional[str] = None) -> None:
        """Feed one historical event (idempotent per slot-day)."""
        slot = _slot_of(kind, summary, ts, place)
        stats = self._slots.setdefault(slot, _SlotStats())
        stats.days.add(int(ts // 86400))
        stats.weekdays.add(slot[0])

    def observe_buffer(self, ring) -> None:
        for buffered in ring.since(0.0):
            ev = buffered.event
            meta = getattr(ev, "meta", None) or {}
            if meta.get("private"):
                continue
            self.observe(getattr(ev, "kind", "memory"),
                         getattr(ev, "summary", ""),
                         buffered.ts, meta.get("place"))

    # -- predicting ----------------------------------------------------------

    def predict(self, now: Optional[float] = None,
                lookahead_h: float = LOOKAHEAD_H) -> list[Prediction]:
        """Future ghosts inside the dial's window, precision-gated."""
        now = now if now is not None else self._now()
        self._expire(now)
        tm = time.gmtime(now)
        out: list[Prediction] = []
        for slot, stats in self._slots.items():
            weekday, hour, kind, _head, place = slot
            if len(stats.days) < MIN_DAYS or stats.suppressed():
                continue
            daily = len(stats.weekdays) >= DAILY_WEEKDAYS
            if not daily and weekday != tm.tm_wday:
                continue
            day_start = now - (tm.tm_hour * 3600 + tm.tm_min * 60
                               + tm.tm_sec)
            expected = day_start + hour * 3600
            hours_until = (expected - now) / 3600.0
            if not 0.0 < hours_until <= lookahead_h:
                continue
            pred = Prediction(expected_ts=expected, kind=kind, slot=slot,
                              confidence=stats.confidence(), place=place)
            self._pending[slot] = pred
            out.append(pred)
        return sorted(out, key=lambda p: p.expected_ts)

    # -- confirm / defy --------------------------------------------------------

    def confirm(self, kind: str, summary: str, ts: float,
                place: Optional[str] = None) -> bool:
        """A real event landed: if it matches a pending prediction the
        ghost hardens (retires — the genuine mark takes its place) and
        the slot earns trust."""
        slot = _slot_of(kind, summary, ts, place)
        pred = self._pending.get(slot)
        if pred is not None and abs(ts - pred.expected_ts) <= CONFIRM_TOL_S:
            self._slots[slot].hits += 1
            del self._pending[slot]
            self.observe(kind, summary, ts, place)
            return True
        self.observe(kind, summary, ts, place)
        return False

    def _expire(self, now: float) -> None:
        """Predictions whose hour passed unconfirmed dissolve — and the
        slot remembers being defied."""
        for slot, pred in list(self._pending.items()):
            if now > pred.expected_ts + CONFIRM_TOL_S:
                self._slots[slot].misses += 1
                del self._pending[slot]

    def pending(self) -> list[Prediction]:
        return list(self._pending.values())
