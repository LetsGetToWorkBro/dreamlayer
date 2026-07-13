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
    bearing_deg: Optional[float] = None   # 0 = ahead reference, clockwise (IMU seam)
    distance_m: Optional[float] = None    # metres from the anchor drop (IMU seam)
    place: str = ""                       # a plain-words spot ("the north rack")
    ts: float = 0.0

    def has_bearing(self) -> bool:
        return self.bearing_deg is not None and self.distance_m is not None


@dataclass
class WaypathCue:
    found: bool
    subject: str = ""
    distance_m: float = 0.0
    direction: str = ""         # human relative direction, given your heading
    place: str = ""
    text: str = ""              # "12m to your left" or "at the north rack"
    rel_bearing_deg: Optional[float] = None   # 0 = ahead, clockwise; feeds the
                                              # audible cue (hud/spatial_audio)


class WaypathLens:
    """Where is my <thing> / where did I put it.

    Two ways an anchor lands: a precise bearing+distance from the glasses' IMU
    when it saw where you set something down (the hardware seam), or a plain
    spoken spot — "I left my bike at the north rack" — which is what actually
    works pre-hardware. A place-only anchor still answers "where's my bike?"
    with "at the north rack"; a bearing anchor adds the direction + distance.
    """

    def __init__(self, now_fn=None):
        self._now = now_fn or time.time
        self._anchors: dict[str, Anchor] = {}

    def remember(self, subject: str, bearing_deg: Optional[float] = None,
                 distance_m: Optional[float] = None, place: str = "",
                 ts: Optional[float] = None) -> None:
        """Record where a thing (or place) is. Latest wins. Either a
        bearing+distance (from the IMU), a plain `place`, or both."""
        self._anchors[subject.strip().lower()] = Anchor(
            subject=subject.strip(), bearing_deg=bearing_deg, distance_m=distance_m,
            place=place.strip(), ts=ts if ts is not None else self._now())

    def remember_place(self, subject: str, place: str,
                       ts: Optional[float] = None) -> None:
        """The spoken capture path: 'I left my bike at the north rack'. No IMU,
        just the spot in your own words."""
        self.remember(subject, place=place, ts=ts)

    def forget(self, subject: str) -> bool:
        return self._anchors.pop(subject.strip().lower(), None) is not None

    def forget_all(self) -> int:
        """Purge every anchor (the memory-erase hook). Returns how many."""
        n = len(self._anchors)
        self._anchors.clear()
        return n

    def anchors(self) -> list:
        """Every anchor, for persistence and the memories feed."""
        return list(self._anchors.values())

    def locate(self, subject: str, heading_deg: float = 0.0) -> WaypathCue:
        """Where is `subject`, relative to where you're facing?"""
        key = subject.strip().lower()
        anchor = self._anchors.get(key)
        if anchor is None:                    # fuzzy: substring match
            anchor = next((a for k, a in self._anchors.items()
                           if key in k or k in key), None)
        if anchor is None:
            return WaypathCue(found=False, subject=subject)
        if anchor.has_bearing():
            rel = _normalize(anchor.bearing_deg - heading_deg)
            direction = relative_direction(rel)
            dist = round(anchor.distance_m)
            return WaypathCue(
                found=True, subject=anchor.subject, distance_m=anchor.distance_m,
                direction=direction, place=anchor.place,
                text=f"{dist}m {direction}", rel_bearing_deg=rel)
        # place-only anchor — the spoken capture path
        text = f"at {anchor.place}" if anchor.place else "somewhere you saved it"
        return WaypathCue(found=True, subject=anchor.subject, place=anchor.place,
                          text=text)

    def to_hud_card(self, cue: WaypathCue) -> Optional[dict]:
        if not cue.found:
            return None
        from ..hud.spatial_audio import attach_spatial
        card = {
            "type": "WaypathCard",
            "dismiss_ms": 5000,
            "eyebrow": "WAYPATH",
            "primary": cue.subject,
            "detail": cue.text,
            "footer": cue.place,
            "bearing_deg": cue.rel_bearing_deg,
            "color": "accent_memory",
            "lines": ["WAYPATH", cue.subject, cue.text],
        }
        # the audible memory palace: a cue with geometry carries its own
        # positioned-sound parameters, so the phone/buds can render "your bike
        # is behind-left, 11 m" as a sound that comes from there
        return attach_spatial(card, cue.rel_bearing_deg,
                              cue.distance_m if cue.rel_bearing_deg is not None
                              else None)
