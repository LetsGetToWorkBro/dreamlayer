"""memory/source_dawarich.py — where you were, self-hosted (Dawarich).

PlaceReactor and Yesterlight have no real location spine; Dawarich (the standard
self-hosted Google-Timeline replacement) gives the Brain one: "you were at the
coffee shop on Vine when you said that." This source reads recent track points
and answers `at(ts)` — the place you were at a given moment — which memory
surfaces can join against.

Posture: LAN-ONLY, structurally (same `is_local_endpoint` gate as Immich/Home
Assistant) — your location history is the most sensitive stream there is, and
it must never transit the internet from the Brain. Coordinates stay raw here
because they never leave this process. Fetch seam for offline tests; [] / None
fallbacks throughout.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Callable, List, Optional

log = logging.getLogger("dreamlayer.dawarich")

_MAX_BODY = 8 * 1024 * 1024


def _default_fetch(url: str, headers: dict,
                   timeout: float = 4.0) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers=dict(headers or {}))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            return r.read(_MAX_BODY)
    except Exception as exc:                       # noqa: BLE001
        log.debug("[dawarich] fetch failed: %s", exc)
        return None


class DawarichSource:
    """Read a self-hosted Dawarich on the LAN as the Brain's location spine."""

    def __init__(self, base_url: str, api_key: str = "",
                 fetch_fn: Optional[Callable[..., Optional[bytes]]] = None):
        from ..ai_brain.server.backends import is_local_endpoint
        base = (base_url or "").strip().rstrip("/")
        self.base = base if is_local_endpoint(base) else ""
        self._key = (api_key or "").strip()
        self._fetch = fetch_fn or _default_fetch

    @property
    def available(self) -> bool:
        return bool(self.base)

    def points(self, limit: int = 200) -> List[dict]:
        """Newest-first [{ts, lat, lon}] track points, or []."""
        if not self.base:
            return []
        limit = max(1, min(int(limit), 1000))
        q = urllib.parse.urlencode({"api_key": self._key, "per_page": limit,
                                    "order": "desc"})
        raw = self._fetch(f"{self.base}/api/v1/points?{q}",
                          {"Accept": "application/json"})
        if raw is None:
            return []
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return []
        rows = data if isinstance(data, list) else []
        out: List[dict] = []
        for p in rows:
            try:
                ts = p.get("timestamp")
                if isinstance(ts, str):
                    import datetime as _dt
                    ts = _dt.datetime.fromisoformat(
                        ts.replace("Z", "+00:00")).timestamp()
                out.append({"ts": float(ts),
                            "lat": float(p["latitude"]),
                            "lon": float(p["longitude"])})
            except (KeyError, TypeError, ValueError):
                continue                           # one bad point, not the track
        out.sort(key=lambda p: -p["ts"])
        return out[:limit]

    def at(self, ts: float, tolerance_s: float = 1800.0) -> Optional[dict]:
        """Where you were at `ts` (± tolerance), or None — the join key memory
        surfaces use: 'you were HERE when you said that.'"""
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            return None
        best, best_dt = None, float(tolerance_s)
        for p in self.points():
            dt = abs(p["ts"] - ts)
            if dt <= best_dt:
                best, best_dt = p, dt
        return best

    def last(self) -> Optional[dict]:
        pts = self.points(limit=1)
        return pts[0] if pts else None


def default_dawarich(base_url: str = "", api_key: str = "") -> Optional[DawarichSource]:
    s = DawarichSource(base_url, api_key)
    return s if s.available else None
