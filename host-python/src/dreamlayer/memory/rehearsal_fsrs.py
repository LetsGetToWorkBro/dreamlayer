"""memory/rehearsal_fsrs.py — never forget a name: FSRS-scheduled rehearsal.

A memory product should decide WHEN to resurface a memory, not just store it.
This schedules rehearsal of the things you asked Juno to keep (names, faces,
facts) with spaced repetition:

  * baseline — a deterministic expanding-interval scheduler (documented below),
    always available, pure stdlib. Good spacing, not personalized.
  * FSRS     — py-fsrs (the scheduler behind modern Anki; extras group `srs`)
    replaces the interval math with the actual cognitive-science model, fitted
    to how memory decay really behaves. Same store, same API, sharper timing.

The store is a plain JSON file next to the other memory stores. Ratings use the
FSRS vocabulary: "again" (forgot), "hard", "good", "easy". Everything degrades
gracefully — a missing wheel, a corrupt store, or a bad rating never raises into
the Brain; the baseline simply keeps scheduling.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("dreamlayer.rehearsal")

_DAY = 86400.0

# baseline expanding intervals: how the NEXT gap changes per rating.
#   again → back to 10 minutes (you forgot; start over)
#   hard  → keep the current gap (don't grow it yet)
#   good  → double it (floor one day)
#   easy  → grow 2.5x (floor two days)
_RATINGS = ("again", "hard", "good", "easy")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _baseline_next(interval_days: float, rating: str) -> float:
    if rating == "again":
        return 10.0 / 1440.0                      # ten minutes
    if rating == "hard":
        return max(interval_days, 10.0 / 1440.0)
    if rating == "easy":
        return max(2.0, interval_days * 2.5)
    return max(1.0, interval_days * 2.0)          # good (default)


class FsrsEngine:
    """The optional py-fsrs tier. `review(state, rating, now) -> (due_ts, state)`
    or None on any failure — the caller then uses the baseline. `state` is the
    serialized FSRS card (a dict), opaque to the store."""

    dep = "fsrs"
    available = _has("fsrs")

    def __init__(self):
        self._sched: Any = None
        if not self.available:
            return
        try:
            import fsrs  # type: ignore
            maker = getattr(fsrs, "Scheduler", None) or getattr(fsrs, "FSRS", None)
            self._sched = maker() if maker is not None else None
        except Exception as exc:                   # noqa: BLE001
            log.info("[rehearsal] fsrs init failed: %s", exc)
            self._sched = None

    @property
    def ready(self) -> bool:
        return self._sched is not None

    def review(self, state: Optional[dict], rating: str,
               now_ts: float) -> Optional[tuple]:
        if self._sched is None:
            return None
        try:
            import datetime as _dt

            import fsrs  # type: ignore
            Card = fsrs.Card
            Rating = fsrs.Rating
            card = Card.from_dict(state) if (state and hasattr(Card, "from_dict")) \
                else Card()
            r = {"again": Rating.Again, "hard": Rating.Hard,
                 "good": Rating.Good, "easy": Rating.Easy}.get(rating, Rating.Good)
            now = _dt.datetime.fromtimestamp(now_ts, tz=_dt.timezone.utc)
            out = self._sched.review_card(card, r, now)
            card = out[0] if isinstance(out, tuple) else out
            due = getattr(card, "due", None)
            if due is None:
                return None
            due_ts = due.timestamp() if hasattr(due, "timestamp") else float(due)
            new_state = card.to_dict() if hasattr(card, "to_dict") else None
            return (float(due_ts), new_state)
        except Exception as exc:                   # noqa: BLE001
            log.info("[rehearsal] fsrs review failed: %s; baseline takes over", exc)
            return None


class RehearsalScheduler:
    """The store + scheduler. Items are {id, kind, text, due_ts, interval_days,
    reps, fsrs} in one JSON file. All mutators persist immediately and never
    raise; a corrupt store restarts empty (rehearsal is a convenience, not a
    ledger — the memories themselves live elsewhere)."""

    def __init__(self, path, now_fn=time.time, engine: Optional[FsrsEngine] = None):
        self.path = Path(path)
        self._now = now_fn
        self._engine = engine if engine is not None else FsrsEngine()
        self._items: dict[str, dict] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self._items = {str(k): v for k, v in data.items()
                                   if isinstance(v, dict)}
        except Exception as exc:                   # noqa: BLE001
            log.warning("[rehearsal] store unreadable (%s); starting empty", exc)
            self._items = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._items))
        except Exception as exc:                   # noqa: BLE001
            log.error("[rehearsal] save failed: %s", exc)

    # -- API ---------------------------------------------------------------
    @property
    def engine_name(self) -> str:
        return "fsrs" if self._engine.ready else "baseline"

    def add(self, item_id: str, kind: str, text: str) -> Optional[dict]:
        """Start rehearsing something (a name, a fact). First review is due in
        ten minutes — the moment right after meeting someone is when the name
        slips. Re-adding an existing id refreshes its text but keeps schedule."""
        item_id = (item_id or "").strip()
        if not item_id or not (text or "").strip():
            return None
        it = self._items.get(item_id)
        if it is None:
            it = {"id": item_id, "kind": kind or "fact", "text": text.strip(),
                  "due_ts": float(self._now()) + 600.0,
                  "interval_days": 10.0 / 1440.0, "reps": 0, "fsrs": None}
            self._items[item_id] = it
        else:
            it["text"] = text.strip()
        self._save()
        return dict(it)

    def review(self, item_id: str, rating: str) -> Optional[dict]:
        """Record a rehearsal outcome and schedule the next one. Unknown id or
        rating degrades safely (rating falls back to 'good')."""
        it = self._items.get((item_id or "").strip())
        if it is None:
            return None
        rating = rating if rating in _RATINGS else "good"
        now = float(self._now())
        nxt = self._engine.review(it.get("fsrs"), rating, now)
        if nxt is not None and nxt[0] > now:
            it["due_ts"], it["fsrs"] = nxt
            it["interval_days"] = max((it["due_ts"] - now) / _DAY, 10.0 / 1440.0)
        else:                                       # baseline path
            it["interval_days"] = _baseline_next(float(it.get("interval_days", 1.0)),
                                                 rating)
            it["due_ts"] = now + it["interval_days"] * _DAY
        it["reps"] = int(it.get("reps", 0)) + 1
        self._save()
        return dict(it)

    def due(self, limit: int = 5) -> list:
        """What's worth resurfacing right now, most-overdue first — the feed the
        Rehearsal surface / a morning brief reads."""
        now = float(self._now())
        out = [dict(v) for v in self._items.values()
               if float(v.get("due_ts", 0)) <= now]
        out.sort(key=lambda v: float(v.get("due_ts", 0)))
        return out[:max(1, int(limit))]

    def drop(self, item_id: str) -> bool:
        if self._items.pop((item_id or "").strip(), None) is not None:
            self._save()
            return True
        return False

    def all(self) -> list:
        return [dict(v) for v in self._items.values()]


def default_rehearsal(cfg_dir) -> RehearsalScheduler:
    """The Brain's rehearsal store (always works; FSRS sharpens when installed)."""
    return RehearsalScheduler(Path(cfg_dir) / "rehearsal.json")
