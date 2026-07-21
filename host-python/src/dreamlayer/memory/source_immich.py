"""memory/source_immich.py — your photo library as memory (self-hosted Immich).

The largest memory corpus most people already own is their photo library —
faces, places, dates. For anyone self-hosting Immich, this source enriches the
Brain's People and Yesterlight surfaces from it: named people (with how often
they appear) and Immich's own "memories" (on-this-day sets).

Posture: LAN-ONLY, structurally. The base URL must be a local endpoint (the
same `is_local_endpoint` rule the model tier uses); a public URL is refused at
construction, so this source can never make the Brain reach a cloud — Immich's
whole point is that YOU host it. API key rides in a header; HTTP is a seam
(`fetch_fn`) so tests run offline. Everything degrades to [] — never raises.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Callable, List, Optional

log = logging.getLogger("dreamlayer.immich")

_MAX_BODY = 4 * 1024 * 1024


def _default_fetch(url: str, headers: dict,
                   timeout: float = 4.0) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers=dict(headers or {}))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            return r.read(_MAX_BODY)
    except Exception as exc:                       # noqa: BLE001
        log.debug("[immich] fetch failed: %s", exc)
        return None


class ImmichSource:
    """Read a self-hosted Immich on the LAN. A non-local base_url disables the
    source outright (base becomes '')."""

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

    def _get_json(self, path: str):
        if not self.base:
            return None
        headers = {"Accept": "application/json"}
        if self._key:
            headers["x-api-key"] = self._key
        raw = self._fetch(f"{self.base}{path}", headers)
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None

    def people(self, limit: int = 100) -> List[dict]:
        """Named people from your library: [{name, faces}] — the People surface
        merge source. Unnamed face clusters are skipped (no name = no consent to
        surface them by identity — same rule as person_guard)."""
        data = self._get_json("/api/people?withHidden=false")
        rows = data.get("people") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        out: List[dict] = []
        for p in rows:
            try:
                name = str(p.get("name", "") or "").strip()
                if not name:
                    continue
                out.append({"name": name,
                            "faces": int(p.get("assetCount", p.get("faceCount", 0)) or 0)})
            except (TypeError, ValueError, AttributeError):
                continue
        out.sort(key=lambda p: -p["faces"])
        return out[:max(1, int(limit))]

    def memories(self, limit: int = 20) -> List[dict]:
        """Immich's on-this-day memory sets → [{title, ts, count}] for
        Yesterlight. [] when the endpoint is absent (older servers) or empty."""
        data = self._get_json("/api/memories")
        if not isinstance(data, list):
            return []
        out: List[dict] = []
        for m in data:
            try:
                assets = m.get("assets") or []
                ts_raw = str(m.get("memoryAt", m.get("createdAt", "")) or "")
                import datetime as _dt
                ts = _dt.datetime.fromisoformat(
                    ts_raw.replace("Z", "+00:00")).timestamp() if ts_raw else 0.0
                title = str((m.get("data") or {}).get("year", "") or "")
                out.append({"title": (f"On this day, {title}" if title
                                      else "On this day"),
                            "ts": float(ts), "count": len(assets)})
            except Exception:                      # noqa: BLE001 — one bad set, not the batch
                continue
        out.sort(key=lambda m: -float(m["ts"]))
        return out[:max(1, int(limit))]


def default_immich(base_url: str = "", api_key: str = "") -> Optional[ImmichSource]:
    s = ImmichSource(base_url, api_key)
    return s if s.available else None
