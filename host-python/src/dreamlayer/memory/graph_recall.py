"""memory/graph_recall.py — temporal knowledge-graph recall (LightRAG).

Vector recall answers "what's similar"; a knowledge graph answers "what's
connected, and when" — so "what did the doctor say about my knee in March"
resolves by following entity + time edges, not just cosine similarity. Lazy-
imports lightrag (extras group `memory-graph`); absent the wheel, `available`
is False and `answer()` returns None, so the caller falls back to the normal
retriever exactly as today. Fully local (the graph is built by your own local
model + embedder).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.graph_recall")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class GraphRecall:
    """Wrap a LightRAG working directory. `available` is True only when the wheel
    imports AND local model + embedding callables are supplied (LightRAG needs an
    LLM + embedder — we pass the Brain's OWN local ones, so nothing goes to a
    cloud)."""

    dep = "lightrag"
    available = _has("lightrag")

    def __init__(self, workdir: str,
                 llm_fn: Optional[Callable] = None,
                 embed_fn: Optional[Callable] = None):
        self._rag = None
        if not self.available or llm_fn is None or embed_fn is None:
            return
        try:
            from lightrag import LightRAG  # type: ignore
            self._rag = LightRAG(working_dir=str(workdir),
                                 llm_model_func=llm_fn,
                                 embedding_func=embed_fn)
        except Exception as exc:                       # noqa: BLE001
            log.info("[graph_recall] LightRAG init failed: %s", exc)
            self._rag = None

    @property
    def ready(self) -> bool:
        return self._rag is not None

    def index(self, text: str) -> bool:
        """Fold a memory/document into the graph. False when unavailable."""
        if self._rag is None or not (text or "").strip():
            return False
        try:
            self._rag.insert(text)
            return True
        except Exception as exc:                       # noqa: BLE001
            log.error("[graph_recall] insert failed: %s", exc)
            return False

    def answer(self, query: str) -> Optional[str]:
        """Answer over the graph (entity + time edges), or None when the engine
        is absent / the query fails — the caller then uses vector recall."""
        if self._rag is None or not (query or "").strip():
            return None
        try:
            from lightrag import QueryParam  # type: ignore
            out = self._rag.query(query, param=QueryParam(mode="hybrid"))
            # the sync hybrid path returns a str; if a build/config hands back a
            # coroutine or a dict, str() would surface "<coroutine ...>" garbage as
            # the answer — only accept a real string, else fall back to None.
            out = out.strip() if isinstance(out, str) else ""
            return out or None
        except Exception as exc:                       # noqa: BLE001
            log.error("[graph_recall] query failed: %s", exc)
            return None


def default_graph_recall(workdir: str, llm_fn=None, embed_fn=None) -> Optional[GraphRecall]:
    g = GraphRecall(workdir, llm_fn=llm_fn, embed_fn=embed_fn)
    return g if g.ready else None
