"""face_recall/index.py — HNSW cosine contact search index.

Provides a fast in-memory vector index over personal contact embeddings.
Maps to the FAISS HNSW index in the Halo spec (100K contacts, < 10ms).

In production this wraps the FAISS HNSW index.
In test/standalone mode it uses a brute-force cosine search
which is correct for up to ~1000 contacts with no performance issue.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .schema import ContactRecord, MatchResult
from .embedder import cosine_similarity

DEFAULT_THRESHOLD = 0.65      # minimum cosine similarity for a match


class ContactIndex:
    """Vector index over personal contact face embeddings.

    Parameters
    ----------
    threshold : float
        Minimum cosine similarity to accept as a match (default 0.65).
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold
        self._contacts: dict[str, ContactRecord] = {}

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def add(self, contact: ContactRecord) -> None:
        """Add or update a contact in the index."""
        self._contacts[contact.contact_id] = contact

    def remove(self, contact_id: str) -> None:
        """Remove a contact from the index."""
        self._contacts.pop(contact_id, None)

    def load(self, contacts: list[ContactRecord]) -> None:
        """Bulk-load a list of contacts, replacing the current index."""
        self._contacts = {c.contact_id: c for c in contacts}

    @property
    def size(self) -> int:
        return len(self._contacts)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, embedding: list[float]) -> Optional[MatchResult]:
        """Return the best-matching contact, or None if below threshold."""
        if not self._contacts or not embedding:
            return None

        best_id: Optional[str] = None
        best_score: float = 0.0

        for cid, contact in self._contacts.items():
            score = cosine_similarity(embedding, contact.embedding)
            if score > best_score:
                best_score = score
                best_id = cid

        if best_id is None or best_score < self.threshold:
            return None

        return MatchResult(
            contact=self._contacts[best_id],
            confidence=round(best_score, 4),
            is_match=True,
        )

    def search_top_k(self, embedding: list[float],
                     k: int = 3) -> list[MatchResult]:
        """Return the top-k matches above threshold, sorted by confidence."""
        if not self._contacts or not embedding:
            return []

        scored = [
            (cid, cosine_similarity(embedding, c.embedding))
            for cid, c in self._contacts.items()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for cid, score in scored[:k]:
            if score >= self.threshold:
                results.append(MatchResult(
                    contact=self._contacts[cid],
                    confidence=round(score, 4),
                    is_match=True,
                ))
        return results
