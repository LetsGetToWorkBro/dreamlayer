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
from dataclasses import dataclass, replace
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
    # WHERE ON EARTH it was dropped. The bearing/distance pair above is relative
    # to wherever the wearer was standing at the time, so it goes stale the
    # moment they move; a coordinate does not. With this, `locate` can compute a
    # live bearing from the CURRENT position instead of replaying a dead one,
    # which is what makes "12 m to your left" true rather than a fossil.
    lat: Optional[float] = None
    lon: Optional[float] = None

    def has_bearing(self) -> bool:
        return self.bearing_deg is not None and self.distance_m is not None

    def has_coord(self) -> bool:
        return self.lat is not None and self.lon is not None


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
                 ts: Optional[float] = None, lat: Optional[float] = None,
                 lon: Optional[float] = None) -> None:
        """Record where a thing (or place) is. Latest wins. A bearing+distance
        (from the IMU), a plain `place`, a coordinate, or any combination."""
        self._anchors[subject.strip().lower()] = Anchor(
            subject=subject.strip(), bearing_deg=bearing_deg, distance_m=distance_m,
            place=place.strip(), ts=ts if ts is not None else self._now(),
            lat=lat, lon=lon)

    def remember_place(self, subject: str, place: str,
                       ts: Optional[float] = None, lat: Optional[float] = None,
                       lon: Optional[float] = None) -> None:
        """The spoken capture path: 'I left my bike at the north rack'. No IMU
        — the spot in your own words, plus the coordinate if the Brain has a
        current fix, so recall can give a direction as well as a name."""
        self.remember(subject, place=place, ts=ts, lat=lat, lon=lon)

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

    def locate(self, subject: str, heading_deg: float = 0.0,
               here: Optional[dict] = None) -> WaypathCue:
        """Where is `subject`, relative to where you're facing?

        `here` is the wearer's CURRENT position ({lat, lon}). When both it and
        the anchor have coordinates, the bearing and distance are computed live
        — which is the only way they stay true after the wearer has moved. A
        stored bearing is relative to wherever they were standing when they
        dropped it and is worthless the moment they walk away, which is why the
        IMU seam alone was never enough to make this feature honest.
        """
        key = subject.strip().lower()
        anchor = self._anchors.get(key)
        if anchor is None:                    # fuzzy: substring match
            anchor = next((a for k, a in self._anchors.items()
                           if key in k or k in key), None)
        if anchor is None:
            return WaypathCue(found=False, subject=subject)
        # A live fix beats a stored bearing: same branch below, fresher inputs.
        #
        # THE HEADING IS NOT OPTIONAL FOR A DIRECTION WORD, and the two bearing
        # sources differ in a way that is easy to conflate:
        #
        #   * a STORED `bearing_deg` (the IMU seam) is already RELATIVE to where
        #     the wearer was facing when they dropped the anchor, so the
        #     `heading_deg=0` default below is correct for it.
        #   * a bearing COMPUTED from two coordinates is an ABSOLUTE compass
        #     bearing. Subtracting a heading of 0 treats it as relative, which
        #     silently means "assume the wearer faces north" — so a thing due
        #     north of someone facing south was reported as "ahead". A wrong
        #     direction stated confidently is worse than no direction at all.
        #
        # So the computed path fills `distance_m` ALWAYS and `bearing_deg` only
        # when a real heading is known. Without one it falls to the
        # distance-only text below: "152m away · at the rack" is honest, and the
        # distance was never the part that needed a compass.
        if here and anchor.has_coord():
            try:
                from ..ai_brain.server.geo import haversine_m, initial_bearing_deg
                hlat, hlon = float(here["lat"]), float(here["lon"])
                assert anchor.lat is not None and anchor.lon is not None
                head = here.get("heading_deg")
                absolute = initial_bearing_deg(hlat, hlon, anchor.lat, anchor.lon)
                anchor = replace(
                    anchor,
                    distance_m=haversine_m(hlat, hlon, anchor.lat, anchor.lon),
                    bearing_deg=(_normalize(absolute - float(head))
                                 if head is not None else None))
            except Exception:                     # noqa: BLE001 — a missing fix
                pass                              # must never cost the answer
        if anchor.has_bearing():
            # has_bearing() is exactly `bearing_deg is not None and distance_m
            # is not None`, so both are present on this branch.
            assert anchor.bearing_deg is not None and anchor.distance_m is not None
            rel = _normalize(anchor.bearing_deg - heading_deg)
            direction = relative_direction(rel)
            dist = round(anchor.distance_m)
            return WaypathCue(
                found=True, subject=anchor.subject, distance_m=anchor.distance_m,
                direction=direction, place=anchor.place,
                text=f"{dist}m {direction}", rel_bearing_deg=rel)
        # Distance without a direction: a coordinate but no compass heading.
        # Reported rather than dropped — "how far" is most of the answer, and
        # the alternative was inventing a direction from an assumed heading.
        if anchor.distance_m is not None:
            dist = round(anchor.distance_m)
            text = (f"{dist}m away \u00b7 at {anchor.place}" if anchor.place
                    else f"{dist}m away")
            return WaypathCue(found=True, subject=anchor.subject,
                              distance_m=anchor.distance_m, place=anchor.place,
                              text=text)
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
