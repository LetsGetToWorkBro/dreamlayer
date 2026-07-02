from __future__ import annotations
from ..hud import cards
from ..memory.ring_buffer import SemanticRingBuffer, BufferedEvent


class PassiveEventInjector:
    """Turns buffered semantic events into passive HUD surfacing.

    Scans recent events on tick() and emits a card when a strong event clears
    the confidence threshold. Dedupes by db_id so the same cue fires once.
    Later modes (Time-Scrub, Commitment Drift) can swap the scorer without
    changing the loop shape.
    """

    def __init__(self, bridge, ring: SemanticRingBuffer, min_confidence: float = 0.55):
        self.bridge = bridge
        self.ring = ring
        self.min_confidence = float(min_confidence)
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
