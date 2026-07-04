"""plugins/social.py — the store's social layer: ratings, comments, downloads.

Phase 2 of the marketplace (docs/MARKETPLACE.md). The *plugins* stay git-backed
and validated; this adds the CurseForge numbers on top — a small shared service
anyone can host. The canonical hosted version is a Cloudflare Worker
(`registry-api/worker.js`); this module is the **reference implementation and
the contract**, JSON-backed and fully tested, so the behaviour is pinned and a
self-hoster has something to run.

The contract (the Worker mirrors it exactly):

    GET  /api/plugins                 → {plugins:[{name, ...stats}]}   (stats for all)
    GET  /api/plugins/<name>          → {name, ...stats, comments:[…]}
    POST /api/plugins/<name>/rate     {stars, user} → stats           (one vote/user, updatable)
    POST /api/plugins/<name>/comment  {text, user}  → comment
    POST /api/plugins/<name>/download                → {downloads}

`stats` = {downloads, rating, ratings_count, comments_count}. Nothing here
serves plugin *code* — that's the git-backed registry; this is only the numbers.
"""
from __future__ import annotations

import json
import os
from typing import Optional


def _clamp_stars(v) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(1, min(5, n))


class SocialStore:
    """Ratings/comments/downloads, persisted as one small JSON. One rating per
    user per plugin (updatable); comments are append-only; downloads a counter."""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._ratings: dict[str, dict[str, int]] = {}      # name -> user -> stars
        self._downloads: dict[str, int] = {}
        self._comments: dict[str, list] = {}
        self._seq = 0
        self._load()

    # -- writes --------------------------------------------------------------

    def rate(self, name: str, stars, user: str) -> dict:
        s = _clamp_stars(stars)
        if not name or not user or not s:
            return self.stats(name)
        self._ratings.setdefault(name, {})[user] = s
        self._save()
        return self.stats(name)

    def record_download(self, name: str) -> int:
        if name:
            self._downloads[name] = self._downloads.get(name, 0) + 1
            self._save()
        return self._downloads.get(name, 0)

    def add_comment(self, name: str, text: str, user: str,
                    ts: float = 0.0) -> Optional[dict]:
        text = (text or "").strip()
        if not name or not text:
            return None
        self._seq += 1
        c = {"id": self._seq, "user": (user or "anon")[:40],
             "text": text[:2000], "ts": float(ts)}
        self._comments.setdefault(name, []).append(c)
        self._save()
        return c

    # -- reads ---------------------------------------------------------------

    def stats(self, name: str) -> dict:
        votes = list(self._ratings.get(name, {}).values())
        rating = round(sum(votes) / len(votes), 2) if votes else 0.0
        return {"name": name, "downloads": self._downloads.get(name, 0),
                "rating": rating, "ratings_count": len(votes),
                "comments_count": len(self._comments.get(name, []))}

    def comments(self, name: str, limit: int = 50) -> list:
        return list(reversed(self._comments.get(name, [])))[:max(0, limit)]

    def known(self) -> list:
        """Every plugin we've seen any activity on — the registry (the
        catalogue) may be private, so the client merges these stats onto its
        own list. Mirrors the Worker's tracked-names set."""
        names = set(self._ratings) | set(self._downloads) | set(self._comments)
        return sorted(names)

    def apply_to_index(self, entries: list) -> list:
        """Fold live stats into registry index entries (non-mutating)."""
        out = []
        for e in entries or []:
            merged = dict(e)
            merged.update({k: v for k, v in self.stats(e.get("name", "")).items()
                           if k != "name"})
            out.append(merged)
        return out

    # -- persistence (atomic, silent on failure — mirrors the other stores) --

    def to_dict(self) -> dict:
        return {"ratings": self._ratings, "downloads": self._downloads,
                "comments": self._comments, "seq": self._seq}

    def _save(self) -> None:
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.to_dict(), f)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                d = json.load(f)
            self._ratings = {str(k): {str(u): int(s) for u, s in (v or {}).items()}
                             for k, v in (d.get("ratings") or {}).items()}
            self._downloads = {str(k): int(v) for k, v in (d.get("downloads") or {}).items()}
            self._comments = {str(k): list(v or []) for k, v in (d.get("comments") or {}).items()}
            self._seq = int(d.get("seq", 0) or 0)
        except Exception:
            pass


def route(store: SocialStore, method: str, path: str, body: Optional[dict] = None,
          index_entries: Optional[list] = None, ts: float = 0.0) -> tuple:
    """Pure request router — maps (method, path, body) to (status, obj). The
    HTTP server (or the Worker) is a thin shell over this. `index_entries` lets
    GET /api/plugins fold stats into the catalogue."""
    body = body or {}
    parts = [p for p in (path or "").strip("/").split("/") if p]   # api plugins [name] [action]
    if parts[:2] != ["api", "plugins"]:
        return 404, {"error": "not found"}
    rest = parts[2:]
    if method == "GET" and not rest:
        # with a catalogue → fold stats into it; without → stats for known
        # plugins, for the client to merge onto its own (possibly private) list
        if index_entries:
            return 200, {"plugins": store.apply_to_index(index_entries)}
        return 200, {"plugins": [store.stats(n) for n in store.known()]}
    if not rest:
        return 405, {"error": "method not allowed"}
    name = rest[0]
    action = rest[1] if len(rest) > 1 else ""
    if method == "GET" and not action:
        return 200, {**store.stats(name), "comments": store.comments(name)}
    if method == "POST" and action == "rate":
        return 200, store.rate(name, body.get("stars"), str(body.get("user", "")))
    if method == "POST" and action == "download":
        return 200, {"name": name, "downloads": store.record_download(name)}
    if method == "POST" and action == "comment":
        c = store.add_comment(name, str(body.get("text", "")),
                              str(body.get("user", "")), ts=ts)
        return (200, c) if c else (400, {"error": "empty comment"})
    return 404, {"error": "not found"}
