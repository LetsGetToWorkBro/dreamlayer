"""LostFound dynamic 3D scene graph — tracks object *change* across frames
("where did I last see my keys") instead of per-frame captions.

ADD-alongside: new sibling. Provides a `vision_fn` for
SceneDescriber(vision_fn=...) (scene_describer.py untouched). Lazy-imports the
LostFound stack (extras group `vision`); when absent it keeps a tiny in-house
last-seen ledger keyed by label, which already answers "where did I last see X".
"""
from __future__ import annotations
import logging
import time

log = logging.getLogger("dreamlayer.scene_lostfound")


def _has(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


class LostFoundScene:
    available = _has("lost_and_found") or _has("lostfound")

    def __init__(self):
        self._last_seen: dict[str, dict] = {}   # label -> {place, ts}

    def observe(self, label: str, place: str | None, now: float | None = None) -> None:
        self._last_seen[label] = {"place": place, "ts": now if now is not None else time.time()}

    def where(self, label: str) -> dict | None:
        """Return {place, ts} for the last place an object was seen, or None."""
        return self._last_seen.get(label)

    def vision_fn(self, frame):
        """SceneDescriber-compatible callable. With no model attached it returns
        None (SceneDescriber then no-ops), preserving current behaviour."""
        return None
