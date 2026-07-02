"""confluence/taps.py — TapCollector: the button becomes the string.

In Dream Mode with a live bond, single taps on the physical button are
collected into a little rhythm. A pattern completes when the wearer
goes quiet for GAP_S (or hits the pulse cap), and the finished pattern
becomes a TinCan ping.

Only *single* taps feed the collector — double-tap keeps its meaning
(Dream Mode toggle) and long-press keeps its meaning (Privacy Veil),
so TinCan borrows the one gesture Dream Mode leaves unclaimed.
"""
from __future__ import annotations

import time
from typing import Optional

GAP_S = 1.6            # this much quiet finishes the pattern
MAX_TAPS = 5
STALE_S = 6.0          # abandoned fragments evaporate


class TapCollector:
    def __init__(self, now_fn=None) -> None:
        self._now = now_fn or time.time
        self._taps: list[str] = []
        self._last_tap = 0.0

    def collect(self, gesture: str = "single") -> None:
        """Feed one gesture. Unknown gestures are ignored."""
        if gesture != "single":
            return
        now = self._now()
        if self._taps and (now - self._last_tap) > STALE_S:
            self._taps = []
        if len(self._taps) < MAX_TAPS:
            self._taps.append("single")
        self._last_tap = now

    def tick(self, now: Optional[float] = None) -> Optional[list[str]]:
        """A finished pattern, once, when the quiet gap passes."""
        now = now if now is not None else self._now()
        if not self._taps:
            return None
        if (now - self._last_tap) < GAP_S and len(self._taps) < MAX_TAPS:
            return None
        pattern, self._taps = self._taps, []
        return pattern

    def pending(self) -> int:
        return len(self._taps)
