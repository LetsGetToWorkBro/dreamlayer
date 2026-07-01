"""dream_mode/ghost_layer.py — Ghost Layer: place-triggered memory echoes.

On every tick, checks whether the current place_signature matches any
stored WorldAnchor. If it does, emits a WorldAnchorCard to the HUD.
"""
from __future__ import annotations
import time
from typing import Optional

COOLDOWN_S = 30.0


class GhostLayer:
    """Surfaces memory echoes when revisiting known places."""

    def __init__(self, db=None, privacy=None, cooldown_s: float = COOLDOWN_S):
        self._db = db
        self._privacy = privacy
        self._cooldown_s = cooldown_s
        self._last_emit: dict[str, float] = {}

    def tick(self, ctx) -> Optional[dict]:
        if self._privacy and not self._privacy.allow_capture():
            return None
        if not ctx.place_signature or not ctx.world_anchors:
            return None
        for anchor in ctx.world_anchors:
            sig = anchor.get("signature", "")
            if sig != ctx.place_signature:
                continue
            now = time.monotonic()
            if now - self._last_emit.get(sig, 0.0) < self._cooldown_s:
                continue
            self._last_emit[sig] = now
            return self._build_card(anchor)
        return None

    def _build_card(self, anchor: dict) -> dict:
        return {
            "type": "WorldAnchorCard",
            "dismiss_ms": 6000,
            "eyebrow": "GHOST LAYER",
            "primary": anchor.get("title", "Memory"),
            "detail": anchor.get("summary", ""),
            "footer": anchor.get("date", ""),
            "color": 0x5EF7,
            "opacity": 0.85,
            "anchor_id": anchor.get("id"),
            "lines": [
                "GHOST LAYER",
                anchor.get("title", "Memory"),
                anchor.get("summary", ""),
            ],
            "layout": {
                "eyebrow": {"x": 128, "y": 196, "size": "sm",
                            "color": 0x5EF7, "tracking": 3},
                "primary": {"x": 128, "y": 214, "size": "sm",
                            "color": 0xFFFF},
                "detail":  {"x": 128, "y": 230, "size": "sm",
                            "color": 0x39E7},
                "footer":  {"x": 128, "y": 246, "size": "sm",
                            "color": 0x5EF7},
            },
        }
