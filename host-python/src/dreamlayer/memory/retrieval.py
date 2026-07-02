from __future__ import annotations
import json
from .embeddings import MockEmbeddingProvider, cosine
class Retriever:
    def __init__(self, db, embedder=None):
        self.db = db; self.embedder = embedder or MockEmbeddingProvider()
    def search(self, query: str, kind=None, top_k=3):
        qv = self.embedder.embed(query)
        scored = []
        for m in self.db.memories(kind=kind):
            emb = json.loads(m["embedding"]) if m.get("embedding") else self.embedder.embed(m["summary"])
            sim = cosine(qv, emb)
            score = 0.5*sim + 0.5*(m.get("confidence") or 0.5)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]
