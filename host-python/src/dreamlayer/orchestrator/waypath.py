"""waypath.py — Waypath Lens: where is it / where do I go.

"Your keys are 12m to your left." "The exit is behind you." Point-me-to-my-
own-things (and simple in-place wayfinding) from the anchors DreamLayer
already drops when it sees where you left something. Given your current
heading, an anchor's stored bearing becomes a human direction.

This is the recall half of Memory pointed at space: you ask where a thing is
and get a direction + distance, not a memory card. Anchors are your own; a
thing you never saved has no waypath.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

# 8-point relative directions, 45° sectors centred on "ahead" (0°)
_DIRECTIONS = [
    (0, "ahead"), (45, "ahead and right"), (90, "to your right"),
    (135, "behind you, right"), (180, "behind you"),
    (225, "behind you, left"), (270, "to your left"),
    (315, "ahead and left"), (360, "ahead"),
]


def _normalize(deg: float) -> float:
    return ((deg + 180.0) % 360.0) - 180.0


def relative_direction(rel_bearing_deg: float) -> str:
    d = rel_bearing_deg % 360.0
    return min(_DIRECTIONS, key=lambda s: abs(s[0] - d))[1]


@dataclass
class Anchor:
    subject: str
    bearing_deg: float          # 0 = north/ahead reference, clockwise
    distance_m: float
    place: str = ""
    ts: float = 0.0


@dataclass
class WaypathCue:
    found: bool
    subject: str = ""
    distance_m: float = 0.0
    direction: str = ""         # human relative direction, given your heading
    place: str = ""
    text: str = ""              # "12m to your left"


class WaypathLens:
    def __init__(self, now_fn=None):
        self._now = now_fn or time.time
        self._anchors: dict[str, Anchor] = {}

    def remember(self, subject: str, bearing_deg: float, distance_m: float,
                 place: str = "", ts: Optional[float] = None) -> None:
        """Record where a thing (or place) is. Latest wins."""
        self._anchors[subject.strip().lower()] = Anchor(
            subject=subject, bearing_deg=bearing_deg, distance_m=distance_m,
            place=place, ts=ts if ts is not None else self._now())

    def locate(self, subject: str, heading_deg: float = 0.0) -> WaypathCue:
        """Where is `subject`, relative to where you're facing?"""
        key = subject.strip().lower()
        anchor = self._anchors.get(key)
        if anchor is None:                    # fuzzy: substring match
            anchor = next((a for k, a in self._anchors.items()
                           if key in k or k in key), None)
        if anchor is None:
            return WaypathCue(found=False, subject=subject)
        rel = _normalize(anchor.bearing_deg - heading_deg)
        direction = relative_direction(rel)
        dist = round(anchor.distance_m)
        return WaypathCue(
            found=True, subject=anchor.subject, distance_m=anchor.distance_m,
            direction=direction, place=anchor.place,
            text=f"{dist}m {direction}")

    def to_hud_card(self, cue: WaypathCue) -> Optional[dict]:
        if not cue.found:
            return None
        return {
            "type": "WaypathCard",
            "dismiss_ms": 5000,
            "eyebrow": "WAYPATH",
            "primary": cue.subject,
            "detail": cue.text,
            "footer": cue.place,
            "bearing_deg": None,
            "color": "accent_memory",
            "lines": ["WAYPATH", cue.subject, cue.text],
        }
