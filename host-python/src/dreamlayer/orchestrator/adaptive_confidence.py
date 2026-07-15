"""app/adaptive_confidence.py

DismissalTracker — sliding window feedback loop.

Listens to outbound telemetry events (CARD_SHOWN / CARD_DISMISSED) that
ble/telemetry.lua emits and adjusts per-card-type confidence thresholds so
the memory engine stops surfacing cards the user consistently ignores.

Algorithm
---------
- Maintain a PER-CARD-TYPE deque of events, each capped at WINDOW_SIZE
  (P2-15: one shared window let a chatty card type evict every other
  type's history, so a rarely-shown type could never accumulate the
  MIN_SAMPLES it needs to adapt — each type now remembers its own last
  WINDOW_SIZE events, and a burst of one type cannot erase another's).
- dismissal_rate(card_type) = dismissed / shown for that type's window.
- suggested_threshold(card_type, base) lifts the base threshold by up to
  MAX_LIFT when dismissal_rate >= HIGH_DISMISS_RATE.
- Threshold is never lowered below base (only raised) — conservative.
- Distinct types are bounded at MAX_TYPES (LRU-evicted) so a hostile or
  buggy stream of unique card_type strings cannot grow memory unboundedly.

Persistence
-----------
Writes the per-type windows to ~/.dreamlayer/dismissal_log.json on every
update so they survive process restarts (atomic rename). Loads either the
v2 per-type format or the legacy flat list, folding the latter per type.

Usage
-----
    tracker = DismissalTracker()
    # Wire to telemetry stream:
    bridge.on_telemetry(tracker.on_telemetry_event)
    # Query before recall:
    threshold = tracker.suggested_threshold("ObjectRecallCard", base=0.45)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional

log = logging.getLogger("dreamlayer.adaptive_confidence")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WINDOW_SIZE        = 20      # sliding window depth (PER card type)
MAX_TYPES          = 32      # distinct card types remembered (LRU-evicted)
HIGH_DISMISS_RATE  = 0.60    # >= 60% dismissed → start lifting threshold
MAX_LIFT           = 0.25    # maximum threshold increase (absolute)
MIN_SAMPLES        = 3       # need at least this many shown before adjusting
_DEFAULT_LOG_PATH  = Path.home() / ".dreamlayer" / "dismissal_log.json"

# Telemetry event names (mirrors ble/telemetry.lua constants)
_EV_SHOWN     = "CARD_SHOWN"
_EV_DISMISSED = "CARD_DISMISSED"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class _Event:
    card_type: str
    event: str   # _EV_SHOWN or _EV_DISMISSED


# ---------------------------------------------------------------------------
# DismissalTracker
# ---------------------------------------------------------------------------
class DismissalTracker:
    """Sliding-window dismissal tracker with adaptive threshold output."""

    def __init__(
        self,
        window_size: int = WINDOW_SIZE,
        log_path: Optional[Path] = None,
        persist: bool = True,
        max_types: int = MAX_TYPES,
    ) -> None:
        # insertion order doubles as LRU order: appending to a type moves it
        # to the end (see _window_for), so the first key is the stalest type
        self._windows: dict[str, Deque[_Event]] = {}
        self._window_size = window_size
        self._max_types = max(1, int(max_types))
        self._log_path = Path(log_path) if log_path else _DEFAULT_LOG_PATH
        self._persist = persist
        self._listeners: list[Callable[[str, float], None]] = []
        if persist:
            self._load()

    def _window_for(self, card_type: str) -> Deque[_Event]:
        w = self._windows.pop(card_type, None)
        if w is None:
            w = deque(maxlen=self._window_size)
            while len(self._windows) >= self._max_types:
                self._windows.pop(next(iter(self._windows)))   # LRU evict
        self._windows[card_type] = w                            # move to MRU
        return w

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def on_telemetry_event(self, msg: dict) -> None:
        """Ingest a raw TEL dict from ble/telemetry outbound stream.

        Expected shape: {t: "TEL", event: str, card_type: str, ...}
        Silently ignores non-TEL or non-card events.
        """
        if not isinstance(msg, dict):
            return
        if msg.get("t") != "TEL":
            return
        ev = msg.get("event", "")
        if ev not in (_EV_SHOWN, _EV_DISMISSED):
            return
        card_type = msg.get("card_type", "")
        if not card_type:
            return

        self._window_for(card_type).append(_Event(card_type=card_type, event=ev))
        if self._persist:
            self._save()

        # Notify threshold-change listeners. A listener is arbitrary caller
        # code, so one that raises must not break the fan-out or the telemetry
        # ingest — but a silent swallow hid every broken listener (audit
        # 2026-07-14). Keep isolating them; make the failure observable.
        for cb in self._listeners:
            try:
                base = 0.45  # sensible default; callers can re-query directly
                cb(card_type, self.suggested_threshold(card_type, base))
            except Exception:
                log.warning("threshold-change listener %r failed", cb,
                            exc_info=True)

    def on_threshold_change(self, cb: Callable[[str, float], None]) -> None:
        """Register a callback(card_type, new_threshold) for threshold updates."""
        self._listeners.append(cb)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def dismissal_rate(self, card_type: str) -> float:
        """Fraction of shown cards of this type that were dismissed, in
        this type's own window."""
        shown = dismissed = 0
        for ev in self._windows.get(card_type, ()):
            if ev.event == _EV_SHOWN:
                shown += 1
            elif ev.event == _EV_DISMISSED:
                dismissed += 1
        if shown == 0:
            return 0.0
        return dismissed / shown

    def shown_count(self, card_type: str) -> int:
        """Number of CARD_SHOWN events for this type in its window."""
        return sum(1 for e in self._windows.get(card_type, ())
                   if e.event == _EV_SHOWN)

    def suggested_threshold(self, card_type: str, base: float) -> float:
        """Return an adjusted confidence threshold for card_type.

        Raises the threshold by up to MAX_LIFT proportionally to how far the
        dismissal rate exceeds HIGH_DISMISS_RATE.  Never lowers below base.
        """
        if self.shown_count(card_type) < MIN_SAMPLES:
            return base
        rate = self.dismissal_rate(card_type)
        if rate < HIGH_DISMISS_RATE:
            return base
        # Linear scale: rate=HIGH_DISMISS_RATE → lift=0, rate=1.0 → lift=MAX_LIFT
        excess = (rate - HIGH_DISMISS_RATE) / (1.0 - HIGH_DISMISS_RATE)
        lift = excess * MAX_LIFT
        return min(base + lift, 0.95)  # hard cap so we never block everything

    def window_snapshot(self) -> list[dict]:
        """All windows flattened to a list of dicts (debugging / tests)."""
        return [{"card_type": e.card_type, "event": e.event}
                for w in self._windows.values() for e in w]

    def clear(self) -> None:
        """Reset every window and delete the persisted log."""
        self._windows.clear()
        if self._persist and self._log_path.exists():
            self._log_path.unlink()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({
                "v": 2,
                "windows": {t: [{"e": e.event} for e in w]
                            for t, w in self._windows.items()},
            })
            # atomic write via temp file + rename
            fd, tmp = tempfile.mkstemp(dir=self._log_path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(payload)
                os.replace(tmp, self._log_path)
            except OSError:
                # clean up the temp file on a failed write; the outer handler
                # logs the underlying fault.
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            # persistence is best-effort — a disk/permission fault must never
            # crash the telemetry loop — but log it at debug so it isn't wholly
            # invisible (audit 2026-07-14). Narrowed to OSError so a programming
            # error (e.g. a non-serialisable payload) still surfaces loudly.
            log.debug("dismissal-log persist failed: %s", exc)

    def _load(self) -> None:
        try:
            if not self._log_path.exists():
                return
            raw = json.loads(self._log_path.read_text())
            if isinstance(raw, dict) and raw.get("v") == 2:
                for t, events in (raw.get("windows") or {}).items():
                    w = self._window_for(str(t))
                    for item in events[-(self._window_size):]:
                        w.append(_Event(card_type=str(t), event=item["e"]))
            elif isinstance(raw, list):
                # legacy flat list: fold per type, newest-last order preserved
                for item in raw:
                    self._window_for(item["c"]).append(
                        _Event(card_type=item["c"], event=item["e"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # a corrupt/unreadable log means "start fresh", not a crash — but
            # say so, don't discard it silently (audit 2026-07-14). Narrowed to
            # the deserialisation/IO faults a bad file actually produces so a
            # real bug here isn't mistaken for corrupt data.
            log.warning("could not load dismissal log %s (%s); starting fresh",
                        self._log_path, exc)


# ---------------------------------------------------------------------------
# Module-level singleton (wired at app boot)
# ---------------------------------------------------------------------------
_global_tracker: Optional[DismissalTracker] = None


def get_tracker(persist: bool = True) -> DismissalTracker:
    """Return the global DismissalTracker, creating it on first call."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = DismissalTracker(persist=persist)
    return _global_tracker


def reset_global_tracker() -> None:
    """Reset singleton (test helper)."""
    global _global_tracker
    _global_tracker = None
