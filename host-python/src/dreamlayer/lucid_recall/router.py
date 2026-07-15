"""lucid_recall/router.py — LucidRecall query router.

Routes incoming queries to SocialLens, MemoryIndex, or both,
then assembles a LucidRecallResult for HUD display.
"""
from __future__ import annotations
import re
from typing import Optional
import numpy as np
from .schema import LucidRecallResult, QueryType

# Single-word cues, matched on WORD BOUNDARIES (not substrings): the old
# `k in lower` matched "name" inside "tour-name-nt" and "who" inside "whole",
# so ordinary fact questions were misrouted to face-ID and then dead-ended.
FACE_WORDS = {"who", "whos", "name", "person"}
FACT_WORDS = {"what", "when", "where", "how", "why", "recall", "discussed"}
# Multi-word cues, matched as phrases.
FACE_PHRASES = ("who's", "this person", "do i know", "have we met", "remind me")
FACT_PHRASES = ("tell me", "last time", "talked about")

# retained for backwards-compatible imports
FACE_KEYWORDS = FACE_WORDS | set(FACE_PHRASES)
FACT_KEYWORDS = FACT_WORDS | set(FACT_PHRASES)


class LucidRecall:
    """On-demand query router for face/name/fact retrieval.

    Parameters
    ----------
    social_lens : SocialLens, optional
        Handles face/person queries.
    memory_index : object, optional
        Handles fact/context queries (get(query) -> str).
    """

    def __init__(self, social_lens=None, memory_index=None, privacy=None,
                 classify_fn=None):
        self._social = social_lens
        self._memory = memory_index
        # The module NAMED for recall must honor the recall gate: a full pause
        # veil silences read-back (incognito still recalls). Without this,
        # query() returned kept facts and contact names with no pause check
        # (audit 2026-07-14). Default to the ONE shared permissive gate rather
        # than an ad-hoc `privacy is None` fail-open idiom: no gate wired
        # (isolated/library use) resolves to AlwaysOnGate — one primitive to
        # audit — while production always injects the real PrivacyGate.
        from ..memory.privacy import AlwaysOnGate
        self._privacy = privacy or AlwaysOnGate()
        # Pluggable classifier seam (Arch: the three lucid_recall pieces now
        # compose behind this one surface). classify_fn(text) -> QueryType | None
        # lets a semantic router (usearch DenseRouter) replace the keyword
        # heuristic; None keeps the dependency-free keyword _classify default,
        # so the offline path is byte-identical.
        self._classify_fn = classify_fn

    def query(self, text: Optional[str] = None,
              camera_frame: Optional[np.ndarray] = None) -> LucidRecallResult:
        """Route a query and return a LucidRecallResult. Silenced while the full
        pause veil is up — recall is read-back, and the veil means deaf and
        blind."""
        if not self._privacy.allow_recall():
            return LucidRecallResult(query_type=QueryType.UNKNOWN,
                                     answer="No result", confidence=0.0,
                                     source=None)
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

        # Fact query — OR a face query with no camera to consume: fall through
        # to memory rather than returning a dead "No result". A face question
        # ("who did I meet") with nothing to look at is still worth a memory
        # lookup ("you met Sarah at the expo").
        if self._memory and (
                qtype in (QueryType.FACT, QueryType.CONTEXT)
                or (qtype == QueryType.FACE and camera_frame is None)):
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
        if self._classify_fn is not None:
            # a wired semantic router (DenseRouter) gets first say; fall back to
            # the keyword heuristic only when it abstains (returns None).
            qt = self._classify_fn(text)
            if isinstance(qt, QueryType):
                return qt
        lower = text.lower()
        tokens = set(re.findall(r"[a-z']+", lower))
        face = bool(tokens & FACE_WORDS) or any(p in lower for p in FACE_PHRASES)
        fact = bool(tokens & FACT_WORDS) or any(p in lower for p in FACT_PHRASES)
        # Prefer FACT when a query carries both cues (e.g. "who did I talk to
        # about the lease") — it is answerable from memory; the query() layer
        # still routes to the camera first when a frame is present.
        if fact:
            return QueryType.FACT
        if face:
            return QueryType.FACE
        return QueryType.UNKNOWN
