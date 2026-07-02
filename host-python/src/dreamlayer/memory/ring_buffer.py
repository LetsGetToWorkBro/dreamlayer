from __future__ import annotations
from dataclasses import dataclass, field
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
    """

    def __init__(self, capacity: int = 64):
        self.capacity = max(1, int(capacity))
        self._buf: deque[BufferedEvent] = deque(maxlen=self.capacity)

    def append(self, event: MemoryEvent, *, ts: float | None = None, source: str = "passive") -> None:
        self._buf.append(BufferedEvent(
            event=event,
            ts=time.time() if ts is None else ts,
            source=source,
        ))

    def extend(self, events: Iterable[MemoryEvent], *, ts: float | None = None, source: str = "passive") -> None:
        stamp = time.time() if ts is None else ts
        for ev in events:
            self.append(ev, ts=stamp, source=source)

    def latest(self, kind: str | None = None, limit: int = 10) -> list[BufferedEvent]:
        out = list(self._buf)
        if kind:
            out = [b for b in out if b.event.kind == kind]
        return list(reversed(out))[:limit]

    def since(self, cutoff_ts: float, kind: str | None = None) -> list[BufferedEvent]:
        out = [b for b in self._buf if b.ts >= cutoff_ts]
        if kind:
            out = [b for b in out if b.event.kind == kind]
        return out

    def __len__(self) -> int:
        return len(self._buf)
