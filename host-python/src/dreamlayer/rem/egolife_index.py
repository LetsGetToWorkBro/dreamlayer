"""EgoLife-style temporal index — "what did I do over the last week" as a
first-class query over dated memory events.

ADD-alongside: brand-new file. No hard dep (EgoLife is a research pipeline);
this is a self-contained day/week bucketer over memory rows, a seam an EgoGPT
backend can enrich later.
"""
from __future__ import annotations
import time


class EgoLifeIndex:
    available = True

    DAY = 86400

    def __init__(self):
        self._events: list[dict] = []  # each: {ts, kind, text}

    def add(self, ts: float, kind: str, text: str) -> None:
        self._events.append({"ts": float(ts), "kind": kind, "text": text})

    def window(self, days: int = 7, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        cutoff = now - days * self.DAY
        return sorted((e for e in self._events if e["ts"] >= cutoff),
                      key=lambda e: e["ts"], reverse=True)

    def by_day(self, days: int = 7, now: float | None = None) -> dict[int, list[dict]]:
        """Group recent events into day buckets (0 = today, 1 = yesterday, ...)."""
        now = time.time() if now is None else now
        out: dict[int, list[dict]] = {}
        for e in self.window(days=days, now=now):
            bucket = int((now - e["ts"]) // self.DAY)
            out.setdefault(bucket, []).append(e)
        return out
