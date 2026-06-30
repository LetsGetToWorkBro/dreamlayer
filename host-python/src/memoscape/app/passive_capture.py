from __future__ import annotations
import time
from ..memory.privacy import PrivacyGate
from ..memory.ring_buffer import SemanticRingBuffer


class SilentCapture:
    """Privacy-gated, rate-limited passive ingestion entrypoint.

    Accepts scene dicts or transcript strings, converts them to MemoryEvents
    via the existing orchestrator ingestion methods, and stores only semantic
    events in the in-memory ring buffer. No raw media persists.
    """

    def __init__(
        self,
        orchestrator,
        ring: SemanticRingBuffer,
        privacy: PrivacyGate,
        min_interval_ms: int = 4000,
    ):
        self.orch = orchestrator
        self.ring = ring
        self.privacy = privacy
        self.min_interval_ms = max(0, int(min_interval_ms))
        self._last_capture_ms: int | None = None  # None = never captured

    def _allow_now(self, now_ms: int) -> bool:
        if not self.privacy.allow_capture():
            return False
        # Always allow the very first capture regardless of interval
        if self._last_capture_ms is None:
            self._last_capture_ms = now_ms
            return True
        if (now_ms - self._last_capture_ms) < self.min_interval_ms:
            return False
        self._last_capture_ms = now_ms
        return True

    def capture_scene(self, scene: dict, *, now_ms: int | None = None) -> int | None:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        if not self._allow_now(now_ms):
            return None
        before_ids = {m["id"] for m in self.orch.db.memories()}
        mid = self.orch.ingest_scene(scene)
        from ..pipelines.ingest import MemoryEvent
        for row in self.orch.db.memories():
            if row["id"] not in before_ids:
                self.ring.append(MemoryEvent(
                    kind=row["kind"],
                    summary=row["summary"],
                    confidence=row["confidence"],
                    meta={},
                    source="passive",
                    db_id=row["id"],
                ))
        return mid

    def capture_transcript(
        self,
        transcript: str,
        *,
        context: dict | None = None,
        now_ms: int | None = None,
    ) -> list[int]:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        if not self._allow_now(now_ms):
            return []
        before_ids = {m["id"] for m in self.orch.db.memories()}
        db_ids = self.orch.ingest_conversation(transcript, context=context)
        from ..pipelines.ingest import MemoryEvent
        for row in self.orch.db.memories():
            if row["id"] not in before_ids:
                self.ring.append(MemoryEvent(
                    kind=row["kind"],
                    summary=row["summary"],
                    confidence=row["confidence"],
                    meta={},
                    source="passive",
                    db_id=row["id"],
                ))
        return db_ids
