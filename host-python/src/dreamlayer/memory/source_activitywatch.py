"""memory/source_activitywatch.py — "what was I working on Tuesday?" (ActivityWatch).

screenpipe's gentler sibling: ActivityWatch tracks app + window-title time,
locally, and has done so trustably for a decade. Its watcher exposes a REST API
on 127.0.0.1:5600 — loopback only, so reading it is NOT egress (same status as
the Brain's own LAN traffic). This source summarizes recent window activity into
memory rows the Brain can index, giving recall a work-context spine at a gentler
privacy gradient than full screen capture.

Everything is defensive: the server absent, a bucket shape we don't recognize,
or a slow reply degrades to [] — never an exception into the ingest loop. The
HTTP layer is a seam (`fetch_fn`) so the logic tests fully offline.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Callable, List, Optional

log = logging.getLogger("dreamlayer.activitywatch")

_BASE = "http://127.0.0.1:5600"
_MAX_TITLE = 200


def _default_fetch(url: str, timeout: float = 2.0) -> Optional[bytes]:
    """Loopback-only GET. The guard is structural: this module only ever builds
    URLs on 127.0.0.1, and refuses anything else defensively."""
    if not url.startswith("http://127.0.0.1"):
        return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as r:
            return r.read(2 * 1024 * 1024)
    except Exception as exc:                       # noqa: BLE001
        log.debug("[aw] fetch failed: %s", exc)
        return None


class ActivityWatchSource:
    """Read the local ActivityWatch server as a memory source."""

    def __init__(self, base: str = _BASE,
                 fetch_fn: Optional[Callable[[str], Optional[bytes]]] = None):
        # structural loopback pin — a config typo must not turn this into egress
        self.base = base if base.startswith("http://127.0.0.1") else _BASE
        self._fetch = fetch_fn or _default_fetch

    @property
    def available(self) -> bool:
        return self._fetch(f"{self.base}/api/0/info") is not None

    def _get_json(self, path: str):
        raw = self._fetch(f"{self.base}{path}")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None

    def buckets(self) -> List[str]:
        """The window-watcher bucket ids (aw-watcher-window / aw-watcher-android)."""
        data = self._get_json("/api/0/buckets")
        if not isinstance(data, dict):
            return []
        return [k for k in data
                if "window" in str(k) or "android" in str(k)]

    def recent(self, limit: int = 50) -> List[dict]:
        """Newest window-activity rows: {ts, kind: "desk", text, app, duration}.
        `text` reads like a memory ("Working in <app> — <title>"). [] when the
        server is absent or a reply is malformed."""
        limit = max(1, min(int(limit), 500))
        out: List[dict] = []
        for bucket in self.buckets():
            events = self._get_json(f"/api/0/buckets/{bucket}/events?limit={limit}")
            if not isinstance(events, list):
                continue
            for ev in events:
                row = self._row(ev)
                if row is not None:
                    out.append(row)
        out.sort(key=lambda r: -r["ts"])
        return out[:limit]

    @staticmethod
    def _row(ev) -> Optional[dict]:
        try:
            data = ev.get("data") or {}
            app = str(data.get("app", "") or "").strip()
            title = str(data.get("title", "") or "").strip()[:_MAX_TITLE]
            if not app and not title:
                return None
            ts_raw = str(ev.get("timestamp", ""))
            import datetime as _dt
            ts = _dt.datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
            dur = float(ev.get("duration", 0) or 0)
            text = f"Working in {app}" + (f" — {title}" if title else "")
            return {"ts": ts, "kind": "desk", "text": text, "app": app,
                    "duration": round(dur, 1)}
        except Exception:                          # noqa: BLE001 — one bad event, not the batch
            return None


def default_desk_source() -> Optional[ActivityWatchSource]:
    s = ActivityWatchSource()
    return s if s.available else None
