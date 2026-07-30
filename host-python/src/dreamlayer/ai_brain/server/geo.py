"""geo.py — where you are, and where a thing is relative to you.

Two features needed the same missing input and neither could have it:

  * **Private zones** (`private_zone_card`) — "capture suspended in this area".
    A card that says capture is suspended has to be able to suspend capture,
    and to know it is in the area at all.
  * **Waypath direction** — `landing/index.html` promises "recalled as direction
    and distance: '12 m to your left'", and `WaypathLens.locate` has computed
    exactly that since it was written. Its bearing branch simply never ran,
    because `Anchor.bearing_deg` / `distance_m` are documented as an "IMU seam"
    and nothing Brain-side ever filled them.

So this holds the current fix and the two pieces of spherical arithmetic that
turn two coordinates into a bearing and a distance. Deliberately tiny and
dependency-free: pulling in geopy or shapely for a haversine would add a wheel
to the install for thirty lines of maths.

WHAT THIS DOES NOT DO. It stores nothing durable. The fix lives in memory on the
Brain and dies with the process — no row, no index entry, no file. A location
history is a far bigger privacy promise than either feature needs, and the
Brain already has a source for one when the wearer wants it (`dawarich_url`,
read-only, on their own LAN).
"""
from __future__ import annotations

import math
import threading
import time
from typing import Optional

EARTH_RADIUS_M = 6_371_008.8            # IUGG mean radius

#: A fix older than this is not where you are any more. Ten minutes is long
#: enough to survive a phone that reports lazily while stationary, and short
#: enough that a stale fix cannot hold a private zone's shield up after you
#: have driven away from it.
FIX_MAX_AGE_S = 600.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing from point 1 to point 2, degrees clockwise from north.

    The FORWARD azimuth, not the straight-line angle on a flat map: over the
    tens of metres Waypath deals in the difference is negligible, but getting
    it right costs nothing and the same function is correct at any range.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def valid_coord(lat, lon) -> bool:
    """Is this a coordinate at all?

    Rejects the two failure modes that actually occur: a phone with no fix
    reporting (0, 0) — which is a real point in the Gulf of Guinea and would put
    a private zone there — and non-numeric junk from a hand-rolled client.
    """
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    return not (abs(lat) < 1e-7 and abs(lon) < 1e-7)


class LastFix:
    """The most recent position report, in memory only.

    Thread-safe because the HTTP server is threaded and the ear, the lens ring
    and the zone check can all read this from different request threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lat: Optional[float] = None
        self._lon: Optional[float] = None
        self._acc: float = 0.0
        self._ts: float = 0.0
        self._heading: Optional[float] = None

    def set(self, lat, lon, accuracy_m=0.0, ts: Optional[float] = None,
            heading_deg=None) -> bool:
        """Record a fix. `heading_deg` is the phone's compass bearing, and it is
        OPTIONAL for a reason: without it, Waypath reports distance and refuses
        to name a direction, rather than assuming the wearer faces north."""
        if not valid_coord(lat, lon):
            return False
        with self._lock:
            self._lat, self._lon = float(lat), float(lon)
            try:
                self._heading = (None if heading_deg is None
                                 else float(heading_deg) % 360.0)
            except (TypeError, ValueError):
                self._heading = None
            try:
                self._acc = max(0.0, float(accuracy_m or 0.0))
            except (TypeError, ValueError):
                self._acc = 0.0
            self._ts = float(ts if ts is not None else time.time())
        return True

    def get(self, max_age_s: float = FIX_MAX_AGE_S) -> Optional[dict]:
        """The fix, or None when there is none or it has gone stale."""
        with self._lock:
            if self._lat is None or self._lon is None:
                return None
            age = time.time() - self._ts
            if max_age_s and age > max_age_s:
                return None
            return {"lat": self._lat, "lon": self._lon,
                    "accuracy_m": self._acc, "ts": self._ts,
                    "heading_deg": self._heading,
                    "age_s": round(age, 1)}

    def clear(self) -> None:
        with self._lock:
            self._lat = self._lon = None
            self._acc = 0.0
            self._ts = 0.0
            self._heading = None


def zone_containing(zones, lat: float, lon: float) -> str:
    """Name of the first private zone this point falls inside, else "".

    A zone with a missing or non-positive radius is SKIPPED rather than treated
    as a point: a zone that can never match is a shield the wearer thinks they
    have and does not, which is the worse of the two failures here.
    """
    if not valid_coord(lat, lon):
        return ""
    for z in zones or []:
        try:
            if not isinstance(z, dict):
                continue
            radius = float(z.get("radius_m") or 0.0)
            if radius <= 0 or not valid_coord(z.get("lat"), z.get("lon")):
                continue
            # Converted AFTER validation rather than narrowed through it: mypy
            # cannot see that `valid_coord` proves these are floatable, and a
            # cast would assert something only the reader can check. The
            # try/except still covers a dict that mutates between the two.
            zlat = float(z["lat"])
            zlon = float(z["lon"])
            if haversine_m(zlat, zlon, float(lat), float(lon)) <= radius:
                return str(z.get("name") or "this area").strip() or "this area"
        except (TypeError, ValueError):
            continue                              # one bad zone, not the rest
    return ""
