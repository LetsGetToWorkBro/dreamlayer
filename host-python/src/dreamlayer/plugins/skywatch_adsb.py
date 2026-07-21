"""plugins/skywatch_adsb.py — the Skywatch lens (adsb.lol): name the plane overhead.

A plane crosses the sky; the glass says "BA286 — a 777 at 34,000 ft, 12 km out."
adsb.lol is community-run, fully open flight data with a free keyless API and
openly licensed history — and if you run your own receiver, the same shape works
fully locally. The egress is one honest, cacheable call: position (rounded to
~1 km) + radius out, nearby aircraft back.

Same connector discipline as open_meteo: pinned host, hardened primitives,
`fetch_fn` seam for offline tests, None-never-raise.
"""
from __future__ import annotations

import json
import math
from typing import Callable, List, Optional

from ._egress import no_redirect_opener, read_capped

HOST = "https://api.adsb.lol"


def build_query(lat: float, lon: float, radius_nm: int = 25) -> Optional[str]:
    """adsb.lol v2 point query. Coordinates rounded to 2 decimals (~1 km) —
    a 25 nm circle doesn't care where in the block you're standing."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    radius_nm = max(1, min(int(radius_nm), 250))
    return f"{HOST}/v2/point/{round(lat, 2)}/{round(lon, 2)}/{radius_nm}"


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def parse_planes(raw: Optional[bytes], lat: float, lon: float,
                 limit: int = 5) -> List[dict]:
    """Nearest-first [{callsign, alt_ft, type, dist_km, speed_kt}], [] on junk.
    Ground traffic and rows without a position are dropped — the lens is about
    the sky, not the taxiway."""
    if not raw:
        return []
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        aircraft = data.get("ac") or []
        out: List[dict] = []
        for a in aircraft:
            try:
                alat, alon = float(a["lat"]), float(a["lon"])
                # a PRESENT-but-null alt_baro must still fall through to
                # alt_geom (refute 2026-07-21 — readsb feeds emit nulls)
                alt = a.get("alt_baro")
                if alt is None:
                    alt = a.get("alt_geom")
                if alt in (None, "ground"):
                    continue
                alt_ft = int(float(alt))
                if alt_ft < 500:
                    continue
                out.append({
                    "callsign": str(a.get("flight", "") or "").strip() or
                                str(a.get("r", "") or "").strip(),
                    "alt_ft": alt_ft,
                    "type": str(a.get("t", "") or "").strip(),
                    "speed_kt": round(float(a.get("gs", 0) or 0)),
                    "dist_km": round(_haversine_km(lat, lon, alat, alon), 1),
                })
            except (KeyError, TypeError, ValueError):
                continue                           # one bad row, not the batch
        out = [p for p in out if p["callsign"]]
        out.sort(key=lambda p: p["dist_km"])
        return out[:max(1, int(limit))]
    except (ValueError, TypeError):
        return []


def _default_fetch(url: str, timeout: float = 6.0) -> Optional[bytes]:
    if not url.startswith(HOST + "/"):
        return None                                # host pin is structural
    try:
        with no_redirect_opener().open(url, timeout=timeout) as r:
            return read_capped(r, 512 * 1024)
    except Exception:                              # noqa: BLE001
        return None


def overhead(lat: float, lon: float, radius_nm: int = 25,
             fetch_fn: Optional[Callable[[str], Optional[bytes]]] = None
             ) -> Optional[dict]:
    """The nearest airborne aircraft right now, or None."""
    url = build_query(lat, lon, radius_nm)
    if url is None:
        return None
    planes = parse_planes((fetch_fn or _default_fetch)(url), lat, lon, limit=1)
    return planes[0] if planes else None


def say_plane(p: Optional[dict]) -> str:
    """The HUD line, or ''. Honest about what adsb gives: callsign, type,
    altitude, distance (route lookup would be a second call — not made)."""
    if not p:
        return ""
    bits = [p["callsign"]]
    if p.get("type"):
        bits.append(f"a {p['type']}")
    bits.append(f"at {p['alt_ft']:,} ft")
    if p.get("dist_km") is not None:
        bits.append(f"{p['dist_km']:g} km out")
    return " — ".join([bits[0], ", ".join(bits[1:])]) + "."
