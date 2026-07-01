"""lucid_recall/router.py — LucidRecall query router.

Routes incoming queries to SocialLens, MemoryIndex, or both,
then assembles a LucidRecallResult for HUD display.
"""
from __future__ import annotations
from typing import Optional
import numpy as np
from .schema import LucidRecallResult, QueryType

# Keywords that route to face/person identification
FACE_KEYWORDS = {
    "who", "who's", "whos", "name", "person", "this person",
    "do i know", "have we met", "remind me",
}
FACT_KEYWORDS = {
    "what", "when", "where", "how", "why", "tell me", "recall",
    "last time", "talked about", "discussed",
}


class LucidRecall:
    """On-demand query router for face/name/fact retrieval.

    Parameters
    ----------
    social_lens : SocialLens, optional
        Handles face/person queries.
    memory_index : object, optional
        Handles fact/context queries (get(query) -> str).
    """

    def __init__(self, social_lens=None, memory_index=None):
        self._social = social_lens
        self._memory = memory_index

    def query(self, text: Optional[str] = None,
              camera_frame: Optional[np.ndarray] = None) -> LucidRecallResult:
        """Route a query and return a LucidRecallResult."""
        qtype = self._classify(text)

        # Face query: use SocialLens
        if qtype == QueryType.FACE and camera_frame is not None and self._social:
            result = self._social.identify(camera_frame)
            if result.match:
                m = result.match
                return LucidRecallResult(
                    query_type=QueryType.FACE,
                    answer=m.contact.name,
                    confidence=m.confidence,
                    contact_id=m.contact.contact_id,
                    contact_name=m.contact.name,
                    detail=m.contact.context_line(),
                    source="social_lens",
                )
            return LucidRecallResult(
                query_type=QueryType.FACE,
                answer="Not in your contacts",
                confidence=0.0,
                source="social_lens",
            )

        # Fact query: use MemoryIndex
        if qtype in (QueryType.FACT, QueryType.CONTEXT) and self._memory:
            answer = self._memory.get(text or "")
            if answer:
                return LucidRecallResult(
                    query_type=qtype,
                    answer=answer,
                    confidence=0.75,
                    source="memory",
                )

        # Fallback
        return LucidRecallResult(
            query_type=QueryType.UNKNOWN,
            answer="No result",
            confidence=0.0,
            source=None,
        )

    def _classify(self, text: Optional[str]) -> QueryType:
        if not text:
            return QueryType.FACE  # default: camera trigger
        lower = text.lower()
        if any(k in lower for k in FACE_KEYWORDS):
            return QueryType.FACE
        if any(k in lower for k in FACT_KEYWORDS):
            return QueryType.FACT
        return QueryType.UNKNOWN
