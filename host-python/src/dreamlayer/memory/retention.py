"""memory/retention.py — the memory lifecycle: hot → warm → cold.

"Structured memory, never raw" is a format claim; this makes it a
LIFECYCLE claim — the honest answer to "what does the device retain about
last March?" is "cold entities, nothing else":

  hot   (24 h)      the semantic ring buffer — the day's raw structured
                    events. Purged after REM runs; REM promotion is the
                    only road out.
  warm  (90 d)      consolidated memories rows. A warm memory the dreamer
                    kept voting for (positive RetrievalBias) survives its
                    window; one the nights ignored expires.
  cold  (forever)   entities — people, places, promises, taught facts.
                    Only an explicit "forget that" removes them.

Everything is policy-driven and pinned rows (`meta.pinned`) never expire.
The sweep is deliberately conservative: when in doubt (no timestamp, no
bias store), it keeps.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime

# memory kinds that are COLD — identity-grade, never swept
COLD_KINDS = frozenset({"person", "promise", "task", "taught", "place"})


@dataclass
class RetentionPolicy:
    hot_hours: float = 24.0
    warm_days: float = 90.0
    cold_kinds: frozenset = COLD_KINDS


@dataclass
class RetentionReport:
    swept: int = 0                    # rows examined
    expired: list = field(default_factory=list)   # ids removed
    kept_promoted: int = 0            # past-window rows saved by REM bias
    kept_cold: int = 0
    kept_pinned: int = 0


def _created_ts(row) -> float | None:
    raw = row.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


class RetentionSweep:
    """Nightly warm-store sweep. `bias` is the REM RetrievalBias — a
    positive bias is the dreamer's vote to keep a memory past its window."""

    def __init__(self, db, policy: RetentionPolicy | None = None,
                 bias=None, now_fn=None, ann=None) -> None:
        self.db = db
        self.policy = policy or RetentionPolicy()
        self.bias = bias
        self._now = now_fn or time.time
        self.ann = ann          # evict expired vectors too, if an index is wired

    def sweep(self) -> RetentionReport:
        report = RetentionReport()
        cutoff = self._now() - self.policy.warm_days * 86400.0
        for m in self.db.memories():
            report.swept += 1
            kind = m.get("kind") or ""
            if kind in self.policy.cold_kinds:
                report.kept_cold += 1
                continue
            meta = {}
            try:
                meta = json.loads(m.get("meta") or "{}")
            except (TypeError, ValueError):
                pass
            if meta.get("pinned"):
                report.kept_pinned += 1
                continue
            ts = _created_ts(m)
            if ts is None or ts >= cutoff:
                continue                      # inside the warm window
            if self.bias is not None and \
                    self.bias.boost_for(kind, m.get("summary") or "") > 0:
                report.kept_promoted += 1     # the nights kept voting for it
                continue
            self.db.purge_memory(m["id"])
            if self.ann is not None:
                self.ann.remove(m["id"])      # don't leave the vector behind
            report.expired.append(m["id"])
        if self.ann is not None and hasattr(self.ann, "flush"):
            # the sweep is a natural quiet point: persist any batched adds so
            # the crash window for recent vectors stays one sweep wide
            self.ann.flush()
        return report

    def purge_hot(self, ring) -> int:
        """Purge ring events older than the hot window (post-REM)."""
        cutoff = self._now() - self.policy.hot_hours * 3600.0
        return ring.purge_before(cutoff)
