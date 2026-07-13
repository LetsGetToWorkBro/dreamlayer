from __future__ import annotations
from time import monotonic as _monotonic

from ..hud import cards
from ..memory.ring_buffer import SemanticRingBuffer, BufferedEvent


class PassiveEventInjector:
    """Turns buffered semantic events into passive HUD surfacing.

    Scans recent events on tick() and emits a card when a strong event clears
    the confidence threshold. Dedupes by db_id so the same cue fires once.
    Later modes (Time-Scrub, Commitment Drift) can swap the scorer without
    changing the loop shape.
    """

    def __init__(self, bridge, ring: SemanticRingBuffer, min_confidence: float = 0.55,
                 tick_interval_ms: int = 0, clock=None):
        self.bridge = bridge
        self.ring = ring
        self.min_confidence = float(min_confidence)
        # The injector enforces its own cadence (P2-15): the config knob
        # passive_tick_interval_ms existed but nothing consumed it — the "~4 Hz"
        # in Orchestrator.tick() was an assumption about the caller, not a
        # guarantee. With the knob wired here, a caller ticking every frame
        # still scans at most once per interval. 0 = scan on every tick (the
        # old behavior; tests that drive tick-by-tick set it explicitly).
        self.tick_interval_s = max(0.0, float(tick_interval_ms) / 1000.0)
        self._clock = clock or _monotonic
        self._last_scan = float("-inf")
        self._last_emitted_db_id: int | None = None

    def _card_for(self, buf: BufferedEvent) -> dict | None:
        ev = buf.event
        meta = ev.meta if isinstance(ev.meta, dict) else {}
        if ev.kind == "object":
            return cards.object_recall({
                "object":    meta.get("object", ev.summary),
                "place":     meta.get("place", ""),
                "detail":    meta.get("detail", ""),
                "last_seen": "Just now",
                "confidence": round(ev.confidence, 2),
            })
        if ev.kind == "task":
            return cards.commitment_recall({
                "person":     meta.get("person", "Someone"),
                "task":       meta.get("task", ev.summary),
                "due":        meta.get("due", ""),
                "confidence": ev.confidence,
            })
        return None

    def tick(self) -> dict | None:
        now = self._clock()
        if now - self._last_scan < self.tick_interval_s:
            return None                      # inside the configured cadence
        self._last_scan = now
        for buf in self.ring.latest(limit=8):
            ev = buf.event
            if ev.confidence < self.min_confidence:
                continue
            if ev.db_id is not None and ev.db_id == self._last_emitted_db_id:
                continue
            card = self._card_for(buf)
            if card is None:
                continue
            self._last_emitted_db_id = ev.db_id
            self.bridge.send_card(card, event="passive_recall")
            return card
        return None
