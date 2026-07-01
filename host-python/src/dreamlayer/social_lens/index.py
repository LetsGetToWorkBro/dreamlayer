"""social_lens/index.py — HNSW cosine contact search index."""
from __future__ import annotations
from typing import Optional
from .schema import ContactRecord, MatchResult
from .embedder import cosine_similarity

DEFAULT_THRESHOLD = 0.65


class ContactIndex:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold
        self._contacts: dict[str, ContactRecord] = {}

    def add(self, contact: ContactRecord) -> None:
        self._contacts[contact.contact_id] = contact

    def remove(self, contact_id: str) -> None:
        self._contacts.pop(contact_id, None)

    def load(self, contacts: list[ContactRecord]) -> None:
        self._contacts = {c.contact_id: c for c in contacts}

    @property
    def size(self) -> int:
        return len(self._contacts)

    def search(self, embedding: list[float]) -> Optional[MatchResult]:
        if not self._contacts or not embedding:
            return None
        best_id, best_score = None, 0.0
        for cid, contact in self._contacts.items():
            score = cosine_similarity(embedding, contact.embedding)
            if score > best_score:
                best_score = score
                best_id = cid
        if best_id is None or best_score < self.threshold:
            return None
        return MatchResult(contact=self._contacts[best_id],
                           confidence=round(best_score, 4), is_match=True)

    def search_top_k(self, embedding: list[float], k: int = 3) -> list[MatchResult]:
        if not self._contacts or not embedding:
            return []
        scored = [(cid, cosine_similarity(embedding, c.embedding))
                  for cid, c in self._contacts.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            MatchResult(contact=self._contacts[cid],
                        confidence=round(score, 4), is_match=True)
            for cid, score in scored[:k] if score >= self.threshold
        ]
