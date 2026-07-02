"""time_scrub.py — navigable cursor over recent SemanticRingBuffer history.

TimeScrubSession wraps ring.since() into an ordered list of semantic nodes
and exposes forward/back/select navigation returning HUD card payloads.
No hardware or API key required — pure ring data.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from ..memory.ring_buffer import SemanticRingBuffer, RingBucket
from ..hud import cards


@dataclass
class ScrubNode:
    index: int
    bucket: RingBucket
    card: dict


class TimeScrubSession:
    """Immutable snapshot of ring history; cursor navigates forward/back."""

    def __init__(
        self,
        ring: SemanticRingBuffer,
        *,
        lookback_s: float = 3600.0,
        now: float | None = None,
    ):
        now = now if now is not None else time.time()
        buckets = ring.since(now - lookback_s)
        # oldest-first for natural forward-time scrub
        buckets = list(reversed(buckets))
        self._nodes: list[ScrubNode] = [
            ScrubNode(
                index=i,
                bucket=b,
                card=_bucket_to_card(b, i, len(buckets)),
            )
            for i, b in enumerate(buckets)
        ]
        self._cursor: int = len(self._nodes) - 1  # start at most-recent

    # ------------------------------------------------------------------ navigation

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def length(self) -> int:
        return len(self._nodes)

    def current(self) -> dict | None:
        if not self._nodes:
            return None
        return self._nodes[self._cursor].card

    def forward(self) -> dict | None:
        """Move one step toward the present. Returns current card or None."""
        if not self._nodes:
            return None
        self._cursor = min(self._cursor + 1, len(self._nodes) - 1)
        return self._nodes[self._cursor].card

    def back(self) -> dict | None:
        """Move one step toward the past. Returns current card or None."""
        if not self._nodes:
            return None
        self._cursor = max(self._cursor - 1, 0)
        return self._nodes[self._cursor].card

    def select(self, index: int) -> dict | None:
        """Jump to a specific node index. Returns card or None if out of range."""
        if not self._nodes or not (0 <= index < len(self._nodes)):
            return None
        self._cursor = index
        return self._nodes[index].card

    def nodes(self) -> list[ScrubNode]:
        return list(self._nodes)


def _bucket_to_card(bucket: RingBucket, index: int, total: int) -> dict:
    """Convert a ring bucket to a TimeScrubNodeCard payload."""
    ev = bucket.event
    meta = ev.meta or {}
    import datetime as _dt
    ts_str = _dt.datetime.fromtimestamp(bucket.ts).strftime("%H:%M")
    return {
        "type":        "TimeScrubNodeCard",
        "dismiss_ms":  0,
        "index":       index,
        "total":       total,
        "kind":        ev.kind,
        "summary":     ev.summary,
        "ts_label":    ts_str,
        "confidence":  ev.confidence,
        "primary":     ev.summary,
        "footer":      ts_str,
        "source":      ev.source,
        "meta":        meta,
        "lines":       [ev.summary, ts_str],
        "layout": {
            "progress": {"value": index / max(total - 1, 1)},
            "eyebrow":  {"x": 128, "y": 56,  "size": "sm",   "color": 0x2CC79A, "tracking": 2},
            "primary":  {"x": 128, "y": 100, "size": "hero", "color": 0xECF0F1},
            "footer":   {"x": 128, "y": 148, "size": "sm",   "color": 0x58686F},
        },
    }
