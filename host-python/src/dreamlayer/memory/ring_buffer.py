from __future__ import annotations
from dataclasses import dataclass, field
import threading
import time
from collections import deque
from typing import Iterable
from ..pipelines.ingest import MemoryEvent


@dataclass
class BufferedEvent:
    event:  MemoryEvent
    ts:     float = field(default_factory=time.time)
    source: str   = "passive"


# Alias — time_scrub.py and commitment_drift.py import RingBucket
RingBucket = BufferedEvent


class SemanticRingBuffer:
    """Fixed-capacity in-memory timeline of semantic events.

    Stores only typed MemoryEvent objects plus timestamps — no raw audio/video.
    This is the shared primitive for passive recall, Time-Scrub, and future
    deviation/gaze features.

    Thread-safety: capture appends on a daemon thread while the REM sweep
    (purge_before) and readers (latest/since) run on others. Every access is
    serialized behind one lock. Without it, purge_before's read-then-rebind
    could drop an append that landed between the two steps, and a reader
    iterating the deque during an append raised "deque mutated during iteration".
    """

    def __init__(self, capacity: int = 64):
        self.capacity = max(1, int(capacity))
        self._buf: deque[BufferedEvent] = deque(maxlen=self.capacity)
        self._lock = threading.RLock()

    def append(self, event: MemoryEvent, *, ts: float | None = None, source: str = "passive") -> None:
        with self._lock:
            self._buf.append(BufferedEvent(
                event=event,
                ts=time.time() if ts is None else ts,
                source=source,
            ))

    def extend(self, events: Iterable[MemoryEvent], *, ts: float | None = None, source: str = "passive") -> None:
        stamp = time.time() if ts is None else ts
        for ev in events:
            self.append(ev, ts=stamp, source=source)

    def clear(self) -> None:
        """Drop every buffered utterance (erase-everything). Lock-guarded."""
        with self._lock:
            self._buf.clear()

    def latest(self, kind: str | None = None, limit: int = 10) -> list[BufferedEvent]:
        with self._lock:
            out = list(self._buf)                 # snapshot under the lock
        if kind:
            out = [b for b in out if b.event.kind == kind]
        return list(reversed(out))[:limit]

    def since(self, cutoff_ts: float, kind: str | None = None) -> list[BufferedEvent]:
        with self._lock:
            out = [b for b in self._buf if b.ts >= cutoff_ts]
        if kind:
            out = [b for b in out if b.event.kind == kind]
        return out

    def purge_before(self, cutoff_ts: float) -> int:
        """Drop events older than cutoff_ts — the hot-store retention window.
        Capacity eviction bounds SIZE; this bounds AGE. Returns count purged.
        Held under the lock so a concurrent append is never lost to the rebind."""
        with self._lock:
            kept = [b for b in self._buf if b.ts >= cutoff_ts]
            purged = len(self._buf) - len(kept)
            if purged:
                self._buf = deque(kept, maxlen=self.capacity)
            return purged

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
