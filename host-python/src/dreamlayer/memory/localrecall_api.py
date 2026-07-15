"""memory/localrecall_api.py — an optional client for a LocalRecall server.

LocalRecall (mudler/LocalRecall) is a small self-hosted REST knowledge base /
RAG memory that pairs with local LLM runtimes. This adapter lets DreamLayer push
memories to, and query, such a server when a builder is running one — while the
built-in `MemoryDB` / `Retriever` stay the default and are untouched.

ADD-alongside: new module. The HTTP transport is injectable; when no server is
configured (or a call fails) it falls back to an in-process store with the same
`add` / `search` surface, so code written against it runs offline and in tests.
Honors the capture guard: `add` refuses when the Veil is down.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Tuple

log = logging.getLogger("dreamlayer.localrecall_api")


def _tokens(text: str) -> set:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split()}


class LocalRecallClient:
    """`base_url` points at a LocalRecall server; when None (or a request
    raises) an in-memory collection is used. `http_post`/`http_get(url, json)`
    are injectable for tests and custom transports."""

    def __init__(self, base_url: Optional[str] = None, collection: str = "dreamlayer",
                 http_post: Optional[Callable] = None, http_get: Optional[Callable] = None,
                 timeout: float = 15.0):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.collection = collection
        self._timeout = timeout
        self._post = http_post
        self._get = http_get
        self._local: List[Tuple[str, dict]] = []     # fallback store

    @property
    def remote(self) -> bool:
        return self.base_url is not None

    def _poster(self) -> Optional[Callable]:
        if self._post is not None:
            return self._post
        if not self.remote:
            return None
        try:
            from ..ai_brain.server.backends import _urllib_post
            return lambda u, p: _urllib_post(u, p, self._timeout)
        except Exception:
            return None

    def add(self, text: str, metadata: Optional[dict] = None, privacy=None) -> bool:
        """Store a memory. Refuses (returns False) when capture is disallowed."""
        if privacy is not None and hasattr(privacy, "allow_capture") \
                and not privacy.allow_capture():
            return False
        meta = dict(metadata or {})
        poster = self._poster()
        if poster is not None:
            try:
                poster(f"{self.base_url}/api/collections/{self.collection}/entries",
                       {"content": text, "metadata": meta})
                return True
            except Exception as exc:
                log.warning("[localrecall] add failed: %s; buffering locally", exc)
        self._local.append((text, meta))
        return True

    def search(self, query: str, top_k: int = 5) -> List[dict]:
        """Return up to `top_k` matches as [{'text','score','metadata'}]."""
        poster = self._poster()
        if poster is not None:
            try:
                out = poster(f"{self.base_url}/api/collections/{self.collection}/search",
                             {"query": query, "max_results": top_k}) or {}
                results = out.get("results") or out.get("entries") or []
                return results[:top_k]
            except Exception as exc:
                log.warning("[localrecall] search failed: %s; local fallback", exc)
        # In-memory token-overlap scoring (deterministic, no deps).
        q = _tokens(query)
        scored: list[dict[str, Any]] = []
        for text, meta in self._local:
            overlap = len(q & _tokens(text))
            if overlap:
                denom = (len(q) or 1)
                scored.append({"text": text, "score": overlap / denom, "metadata": meta})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:top_k]
