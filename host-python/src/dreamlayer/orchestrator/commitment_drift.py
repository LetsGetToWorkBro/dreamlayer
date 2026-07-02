"""commitment_drift.py — age-based decay and state classification for commitments.

Decay is a 0-1 float:
  0.0 = brand new / plenty of time remaining
  1.0 = past due / shattered

State ladder (thresholds configurable via CommitmentDriftEngine constructor):
  blooming   decay < 0.20
  healthy    0.20 <= decay < 0.50
  drifting   0.50 <= decay < 0.75
  cracking   0.75 <= decay < 1.00
  shattered  decay >= 1.00
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from ..memory.ring_buffer import SemanticRingBuffer
from ..pipelines.ingest import MemoryEvent


_STATES = ["blooming", "healthy", "drifting", "cracking", "shattered"]
_THRESHOLDS = [0.20, 0.50, 0.75, 1.00]  # upper bound for each state (shattered = >=1.0)


@dataclass
class DriftRecord:
    event: MemoryEvent
    created_ts: float
    due_ts: float | None
    decay: float = 0.0
    state: str = "blooming"
    surfaced: bool = False


def _classify(decay: float) -> str:
    if decay >= 1.00:
        return "shattered"
    for threshold, state in zip(_THRESHOLDS, _STATES):
        if decay < threshold:
            return state
    return "shattered"


def _parse_due(due_str: str | None, created_ts: float) -> float | None:
    """Very small due-date parser: understands 'Xh', 'Xd', 'tomorrow'."""
    if not due_str:
        return None
    s = due_str.lower().strip()
    if "tomorrow" in s:
        return created_ts + 86400
    import re
    m = re.search(r"(\d+)\s*h", s)
    if m:
        return created_ts + int(m.group(1)) * 3600
    m = re.search(r"(\d+)\s*d", s)
    if m:
        return created_ts + int(m.group(1)) * 86400
    return None


class CommitmentDriftEngine:
    """Track commitment ring events and update their decay scores."""

    _DEFAULT_LIFETIME_S = 48 * 3600  # 48 h fallback when no due date

    def __init__(
        self,
        ring: SemanticRingBuffer,
        *,
        lifetime_s: float = _DEFAULT_LIFETIME_S,
        alert_states: tuple[str, ...] = ("cracking", "shattered"),
    ):
        self.ring = ring
        self.lifetime_s = lifetime_s
        self.alert_states = alert_states
        self._records: dict[int, DriftRecord] = {}  # keyed by ring bucket id

    def _sync(self) -> None:
        """Pull any new commitment events from the ring into _records."""
        seen_ids = set()
        for bucket in self.ring.latest(kind="task", limit=200):
            bid = id(bucket)
            seen_ids.add(bid)
            if bid not in self._records:
                meta = bucket.event.meta or {}
                due_ts = _parse_due(meta.get("due"), bucket.ts)
                self._records[bid] = DriftRecord(
                    event=bucket.event,
                    created_ts=bucket.ts,
                    due_ts=due_ts,
                )
        # prune evicted buckets
        for gone in set(self._records) - seen_ids:
            del self._records[gone]

    def tick(self, now: float | None = None) -> list[DriftRecord]:
        """Recompute decay for all tracked commitments. Returns alert records."""
        now = now if now is not None else time.time()
        self._sync()
        alerts: list[DriftRecord] = []
        for rec in self._records.values():
            if rec.due_ts is not None:
                span = max(rec.due_ts - rec.created_ts, 1.0)
                elapsed = now - rec.created_ts
                rec.decay = min(elapsed / span, 1.0)
            else:
                elapsed = now - rec.created_ts
                rec.decay = min(elapsed / self.lifetime_s, 1.0)
            rec.state = _classify(rec.decay)
            if rec.state in self.alert_states and not rec.surfaced:
                rec.surfaced = True
                alerts.append(rec)
        return alerts

    def all_records(self) -> list[DriftRecord]:
        self._sync()
        return list(self._records.values())
