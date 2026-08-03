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

    def __init__(self, capacity: int = 64, privacy=None):
        self.capacity = max(1, int(capacity))
        self._buf: deque[BufferedEvent] = deque(maxlen=self.capacity)
        self._lock = threading.RLock()
        # `privacy` makes the Veil a TYPE INVARIANT on this ring's capture path
        # rather than a convention every caller has to remember (`typed_models`,
        # the same opt-in `MemoryDB` takes).
        #
        # Every site that appends here checks `allow_capture()` first today —
        # `world_lens._remember_sighting` even re-checks for the TOCTOU case —
        # and the ring itself checks nothing, so the guarantee rests entirely on
        # nobody ever forgetting. That is the shape `person_guard`/`voice_guard`
        # had before they were centralised: a rule enforced at N call sites is a
        # rule that holds until the N+1th.
        #
        # Default None keeps today's behaviour byte-for-byte; it is a tripwire
        # the Brain opts into, not a new refusal for existing callers.
        self._privacy = privacy
        self._veil_checks = 0

    def set_privacy(self, gate) -> None:
        """Attach the veil after construction — the ring is built lazily, before
        the Brain's gate is necessarily to hand."""
        self._privacy = gate

    @property
    def veil_checks(self) -> int:
        """How many appends the type invariant has actually vetted. Zero means
        the tripwire is armed but nothing has crossed it, which is not the same
        as the ring being guarded — `typed_models`' promotion follows this."""
        return self._veil_checks

    def _veil_check(self, event) -> None:
        """Construct the typed record whose existence IS the permission.

        `models_pydantic.MemoryEvent` cannot be built with `allowed=False`, so a
        veiled keep raises here instead of landing in the ring. Raises rather
        than dropping quietly, matching `MemoryDB._veil_check`: a silent refusal
        is a memory the wearer believes was kept and was not.

        The summary is deliberately NOT passed. This object exists only to be
        refused or discarded, and copying the wearer's words into a validation
        record buys nothing.
        """
        if self._privacy is None:
            return
        from .models_pydantic import MemoryEvent as TypedEvent
        try:
            allowed = bool(self._privacy.allow_capture())
        except Exception:                          # noqa: BLE001 — unreadable → veiled
            allowed = False
        TypedEvent(kind=str(getattr(event, "kind", "") or "Note"),
                   confidence=float(getattr(event, "confidence", 0.0) or 0.0),
                   allowed=allowed)
        self._veil_checks += 1

    def append(self, event: MemoryEvent, *, ts: float | None = None, source: str = "passive") -> None:
        self._veil_check(event)
        with self._lock:
            self._buf.append(BufferedEvent(
                event=event,
                ts=time.time() if ts is None else ts,
                source=source,
            ))

    def restore(self, event: MemoryEvent, *, ts: float | None = None,
                source: str = "seed") -> None:
        """Re-hydrate an ALREADY-KEPT memory. Recall, not capture.

        Seeding the ring from rows that are already on disk is not a new keep,
        and the veil's own contract says so: incognito "stops keeping new
        memories, not recalling old ones" (`memory/privacy.PrivacyGate`). Gating
        this on `allow_capture` would leave the ring empty for the whole of a
        veiled session and the lenses would answer "nothing to report" about a
        timeline that exists — a silence that reads as an absence.

        It is not gated on `allow_recall` either, deliberately: nothing is
        disclosed by re-hydrating in-memory state, and every READ of that state
        is separately gated at answer time (`_LensGate.allow_recall`, checked in
        front of each lens). The disclosure boundary is where it already was.
        """
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

    def purge_before(self, cutoff_ts: float, keep_kinds=None) -> int:
        """Drop events older than cutoff_ts — the hot-store retention window.
        Capacity eviction bounds SIZE; this bounds AGE. Returns count purged.
        Held under the lock so a concurrent append is never lost to the rebind.

        `keep_kinds` exempts identity-grade kinds from the AGE bound, so a ring
        can be swept on the same policy `memory/retention.py` applies to the
        rows it mirrors. Without it a 24-hour hot window silently deletes a
        commitment due in three days — the row is cold-forever on disk
        (`retention.COLD_KINDS`) while its ring view expires under it, and the
        lens reading the ring reports the promise simply gone. Capacity still
        bounds an exempt kind, so this cannot grow the buffer without limit.
        Default None keeps the old behaviour: age out everything."""
        keep = frozenset(keep_kinds or ())
        with self._lock:
            kept = [b for b in self._buf
                    if b.ts >= cutoff_ts or b.event.kind in keep]
            purged = len(self._buf) - len(kept)
            if purged:
                self._buf = deque(kept, maxlen=self.capacity)
            return purged

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
