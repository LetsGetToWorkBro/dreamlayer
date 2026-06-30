"""app/adaptive_confidence.py

DismissalTracker — sliding window feedback loop.

Listens to outbound telemetry events (CARD_SHOWN / CARD_DISMISSED) that
ble/telemetry.lua emits and adjusts per-card-type confidence thresholds so
the memory engine stops surfacing cards the user consistently ignores.

Algorithm
---------
- Maintain a deque of (card_type, event) pairs capped at WINDOW_SIZE.
- dismissal_rate(card_type) = dismissed / (shown) for that type in window.
- suggested_threshold(card_type, base) lifts the base threshold by up to
  MAX_LIFT when dismissal_rate >= HIGH_DISMISS_RATE.
- Threshold is never lowered below base (only raised) — conservative.

Persistence
-----------
Writes the raw event deque to ~/.memoscape/dismissal_log.json on every
update so the window survives process restarts.  Uses an atomic rename.

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
import os
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WINDOW_SIZE        = 20      # sliding window depth
HIGH_DISMISS_RATE  = 0.60    # >= 60% dismissed → start lifting threshold
MAX_LIFT           = 0.25    # maximum threshold increase (absolute)
MIN_SAMPLES        = 3       # need at least this many shown before adjusting
_DEFAULT_LOG_PATH  = Path.home() / ".memoscape" / "dismissal_log.json"

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
    ) -> None:
        self._window: Deque[_Event] = deque(maxlen=window_size)
        self._window_size = window_size
        self._log_path = Path(log_path) if log_path else _DEFAULT_LOG_PATH
        self._persist = persist
        self._listeners: list[Callable[[str, float], None]] = []
        if persist:
            self._load()

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

        self._window.append(_Event(card_type=card_type, event=ev))
        if self._persist:
            self._save()

        # Notify threshold-change listeners
        for cb in self._listeners:
            try:
                base = 0.45  # sensible default; callers can re-query directly
                cb(card_type, self.suggested_threshold(card_type, base))
            except Exception:
                pass

    def on_threshold_change(self, cb: Callable[[str, float], None]) -> None:
        """Register a callback(card_type, new_threshold) for threshold updates."""
        self._listeners.append(cb)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def dismissal_rate(self, card_type: str) -> float:
        """Fraction of shown cards of this type that were dismissed, in window."""
        shown = dismissed = 0
        for ev in self._window:
            if ev.card_type != card_type:
                continue
            if ev.event == _EV_SHOWN:
                shown += 1
            elif ev.event == _EV_DISMISSED:
                dismissed += 1
        if shown == 0:
            return 0.0
        return dismissed / shown

    def shown_count(self, card_type: str) -> int:
        """Number of CARD_SHOWN events for this type in the window."""
        return sum(1 for e in self._window if e.card_type == card_type and e.event == _EV_SHOWN)

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
        """Return window as a list of dicts (useful for debugging / tests)."""
        return [{"card_type": e.card_type, "event": e.event} for e in self._window]

    def clear(self) -> None:
        """Reset the window and delete persisted log."""
        self._window.clear()
        if self._persist and self._log_path.exists():
            self._log_path.unlink()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps([{"c": e.card_type, "e": e.event} for e in self._window])
            # atomic write via temp file + rename
            fd, tmp = tempfile.mkstemp(dir=self._log_path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(payload)
                os.replace(tmp, self._log_path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception:
            pass  # persistence is best-effort; never crash main loop

    def _load(self) -> None:
        try:
            if not self._log_path.exists():
                return
            raw = json.loads(self._log_path.read_text())
            for item in raw[-(self._window_size):]:
                self._window.append(_Event(card_type=item["c"], event=item["e"]))
        except Exception:
            pass


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
