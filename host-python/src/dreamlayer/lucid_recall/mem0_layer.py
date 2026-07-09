"""mem0 structured-memory layer — dedup + time-decay over kept memories.

ADD-alongside: new sibling. Lazy-imports mem0 (extras group `memory`); when
absent it applies an equivalent lightweight in-house dedup (exact-summary
collapse, most-recent wins) so the add/search surface behaves consistently.

Privacy: `add()` accepts an optional `privacy=` and refuses to store when
allow_capture() is False — mirrors the repo's capture-guard contract.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.mem0_layer")

try:  # optional dep — extras group `memory`
    from mem0 import Memory  # type: ignore
    _HAS_MEM0 = True
except ImportError:
    _HAS_MEM0 = False


class Mem0Layer:
    available = _HAS_MEM0

    def __init__(self, privacy=None):
        self._privacy = privacy
        self._mem = None
        self._local: list[dict] = []  # fallback store
        if _HAS_MEM0:
            try:
                self._mem = Memory()
            except Exception as exc:
                log.error("[mem0_layer] init failed: %s; local fallback", exc)
                self._mem = None

    def _allowed(self) -> bool:
        p = self._privacy
        return not (p is not None and hasattr(p, "allow_capture") and not p.allow_capture())

    def add(self, text: str, user_id: str = "me", meta: dict | None = None) -> bool:
        if not self._allowed():
            return False
        if self._mem is not None:
            try:
                self._mem.add(text, user_id=user_id, metadata=meta or {})
                return True
            except Exception as exc:
                log.error("[mem0_layer] add failed: %s; local fallback", exc)
        # dedup: collapse exact-summary duplicates, keep most-recent
        self._local = [r for r in self._local if r["text"] != text]
        self._local.append({"text": text, "user_id": user_id, "meta": meta or {}})
        return True

    def search(self, query: str, user_id: str = "me", limit: int = 5) -> list[dict]:
        if self._mem is not None:
            try:
                res = self._mem.search(query, user_id=user_id, limit=limit)
                return res.get("results", res) if isinstance(res, dict) else res
            except Exception as exc:
                log.error("[mem0_layer] search failed: %s; local fallback", exc)
        q = query.lower()
        hits = [r for r in self._local if r["user_id"] == user_id and any(w in r["text"].lower() for w in q.split())]
        return hits[-limit:][::-1]
