"""orchestrator/presence.py — a gaze→presence micro-ledger.

The brief mapped a "gaze" achievement into saga, but `saga.py`'s ACHIEVEMENTS /
_BY_EVENT are import-time module state with no registration hook — adding one
would mean editing that list in place, which the no-modify rule forbids. So this
lands as a NEW, standalone ledger instead: it turns sustained gaze (dwell) on a
target into a lightweight "presence" signal — how much attention a thing/person
has been given — without touching saga.

Pure stdlib, no dependency, injectable clock. Honors the Privacy Veil: while
capture is disallowed, dwell is not recorded.

    p = PresenceLedger()
    p.look("Maya", privacy=veil)      # call repeatedly while gaze holds
    p.look("Maya", privacy=veil)
    p.presence("Maya")                # accumulated attention seconds
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class _Track:
    total: float = 0.0            # accumulated attention seconds
    last_seen: Optional[float] = None   # last gaze timestamp (None = never)
    looks: int = 0               # number of distinct dwells


class PresenceLedger:
    """Accumulate attention time per target from repeated `look()` pings.

    Consecutive looks within `gap_s` extend one dwell (their gaps sum into
    `total`); a longer silence starts a fresh dwell. `present()` lists targets
    whose recent attention crosses a threshold — a cheap 'who/what am I with'.
    """

    def __init__(self, gap_s: float = 2.0, now_fn: Optional[Callable[[], float]] = None):
        self.gap_s = gap_s
        self._now = now_fn or time.monotonic
        self._tracks: Dict[str, _Track] = {}

    def look(self, target: str, privacy=None) -> float:
        """Register a gaze ping at `target`. Returns its accumulated presence.
        The Veil silences recording (returns current total unchanged)."""
        now = self._now()
        t = self._tracks.setdefault(target, _Track())
        if privacy is not None and hasattr(privacy, "allow_capture") \
                and not privacy.allow_capture():
            return t.total
        if t.last_seen is not None and (now - t.last_seen) <= self.gap_s:
            t.total += now - t.last_seen        # extend the current dwell
        else:
            t.looks += 1                        # a new dwell begins
        t.last_seen = now
        return t.total

    def presence(self, target: str) -> float:
        t = self._tracks.get(target)
        return t.total if t else 0.0

    def present(self, min_seconds: float = 1.0,
                within_s: Optional[float] = None) -> List[Tuple[str, float]]:
        """Targets with at least `min_seconds` of attention, most-attended first.
        If `within_s` is set, only those seen that recently are included."""
        now = self._now()
        out = []
        for name, t in self._tracks.items():
            if t.total < min_seconds:
                continue
            assert t.last_seen is not None   # total>0 implies a gaze was recorded
            if within_s is not None and (now - t.last_seen) > within_s:
                continue
            out.append((name, t.total))
        out.sort(key=lambda kv: kv[1], reverse=True)
        return out

    def forget(self, target: str) -> None:
        self._tracks.pop(target, None)
