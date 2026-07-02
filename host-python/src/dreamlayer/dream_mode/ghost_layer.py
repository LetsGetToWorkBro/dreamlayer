"""dream/ghost_layer.py — Place anchors → WorldAnchorCard ghost overlays.

When the user is at a location that has memory anchors in the DB, the
GhostLayer surfaces them as dim ghost cards — without any user query.

This is the deepest integration with the existing memory engine:
  - Uses ProactiveEngine.on_place() signature matching
  - Emits WorldAnchorCard (new card type, dismiss_ms=8000, 20% opacity)
  - Debounces: same anchor not re-shown within GHOST_COOLDOWN seconds
  - Respects PrivacyGate: if allow_capture() is False, no ghosts emitted
  - Multiple anchors: highest confidence surfaced first each tick
"""
from __future__ import annotations

import time
from typing import Optional

from ..orchestrator.recall_context import RecallContext
from ..hud import cards as C

GHOST_COOLDOWN_S    = 120.0   # same anchor suppressed for 2 minutes
MAX_GHOSTS_PER_TICK = 1       # only one ghost per tick to avoid flooding


class GhostLayer:
    """Surfaces memory ghosts at known locations without user prompting."""

    def __init__(self, db=None, privacy=None) -> None:
        self._db      = db
        self._privacy = privacy
        self._shown:  dict[str, float] = {}   # anchor_key → last shown time

    def tick(self, ctx: RecallContext) -> Optional[dict]:
        """Return a WorldAnchorCard if a fresh anchor matches current place.

        Anchors are sorted by confidence descending so the most reliable
        memory is always surfaced first.
        """
        if self._privacy and not self._privacy.allow_capture():
            return None
        if not ctx.world_anchors:
            return None

        now = time.monotonic()

        # Sort by confidence descending — highest confidence shown first
        sorted_anchors = sorted(
            ctx.world_anchors,
            key=lambda a: float(a.get("confidence") or 0.0),
            reverse=True,
        )

        for anchor in sorted_anchors[:MAX_GHOSTS_PER_TICK]:
            key = anchor.get("id") or anchor.get("summary", "")[:40]
            # None (never shown) — a 0.0 sentinel suppresses the first
            # emission on hosts whose monotonic clock is younger than the
            # cooldown (fresh VMs boot with monotonic() < 120s)
            last = self._shown.get(key)
            if last is not None and (now - last) < GHOST_COOLDOWN_S:
                continue
            self._shown[key] = now
            return C.world_anchor_card(
                summary=anchor.get("summary", ""),
                place=anchor.get("place", ""),
                ts_label=anchor.get("ts_label", ""),
                confidence=anchor.get("confidence"),
            )
        return None

    def clear_cache(self) -> None:
        """Reset shown-anchor debounce cache (e.g. on dream exit)."""
        self._shown.clear()
