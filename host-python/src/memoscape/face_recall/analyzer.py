"""face_recall/analyzer.py — FaceRecall main orchestrator.

The single entry point. Called on double-tap (IMU trigger) from the
orchestrator or Dream Engine.

  fr = FaceRecall(contacts)
  result = fr.identify(camera_frame)   # synchronous, < 30ms on-device
  card   = result.to_hud_card()        # send to HUD renderer

Pipeline
--------
  Stage 1  embed_frame()      → 512-d embedding + face confidence
  Stage 2  index.search()     → MatchResult or None
  Stage 3  enricher.enrich()  → ContactRecord with last-met + notes
  Stage 4  renderer.render()  → FaceRecallCard dict
  Stage 5  enricher.record_encounter() → update last-met in memory

Latency budget (matches Halo spec)
-----------------------------------
  Halo capture:  10 ms  (hardware)
  Embedding:      8 ms  (NPU stub in software)
  Index search:  10 ms  (HNSW / brute-force for < 1000 contacts)
  Enrich:        <1 ms  (local memory)
  Total:        ~30 ms
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .embedder import FaceEmbedder, embed_frame
from .index import ContactIndex
from .enricher import ContactEnricher
from .renderer import FaceRecallRenderer
from .schema import ContactRecord, FaceRecallResult, MatchResult


class FaceRecall:
    """Personal contacts facial recognition orchestrator.

    Parameters
    ----------
    contacts : list[ContactRecord] or dict, optional
        Personal contacts to match against.
        - list[ContactRecord]: loaded directly
        - dict: {contact_id: {"name": str, "embedding": list, ...}}
          (compatible with LieLens contact_registry format)
    threshold : float
        Minimum cosine similarity for a match (default 0.65).
    memory_backend : object, optional
        Memory backend for last-met / notes enrichment.
    privacy : object, optional
        Privacy controller with allow_capture() -> bool.
    """

    def __init__(
        self,
        contacts=None,
        threshold: float = 0.65,
        memory_backend=None,
        privacy=None,
    ):
        self._embedder = FaceEmbedder(threshold=0.40)
        self._index = ContactIndex(threshold=threshold)
        self._enricher = ContactEnricher(memory_backend)
        self._renderer = FaceRecallRenderer()

        self._privacy = privacy or _AlwaysOn()

        if contacts:
            self._load_contacts(contacts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def identify(self, frame: Optional[np.ndarray]) -> FaceRecallResult:
        """Identify a person from a camera frame.

        Always returns a FaceRecallResult — never raises.
        Check result.no_face / result.no_match / result.match.
        """
        if not self._privacy.allow_capture():
            return FaceRecallResult(match=None, frame_confidence=0.0,
                                    no_face=True)

        # Stage 1: embed
        embedding, face_conf = embed_frame(frame, self._embedder)
        if embedding is None:
            return FaceRecallResult(match=None,
                                    frame_confidence=face_conf,
                                    no_face=True)

        # Stage 2: search
        match = self._index.search(embedding)
        if match is None:
            return FaceRecallResult(match=None,
                                    frame_confidence=face_conf,
                                    no_match=True)

        # Stage 3: enrich
        enriched_contact = self._enricher.enrich(match.contact)
        enriched_match = MatchResult(
            contact=enriched_contact,
            confidence=match.confidence,
            is_match=True,
        )

        # Stage 5: record encounter (update last-met)
        self._enricher.record_encounter(match.contact.contact_id)

        return FaceRecallResult(
            match=enriched_match,
            frame_confidence=face_conf,
        )

    def add_contact(self, contact: ContactRecord) -> None:
        """Add or update a contact in the live index."""
        self._index.add(contact)

    def remove_contact(self, contact_id: str) -> None:
        """Remove a contact from the live index."""
        self._index.remove(contact_id)

    @property
    def contact_count(self) -> int:
        return self._index.size

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_contacts(self, contacts) -> None:
        if isinstance(contacts, list):
            self._index.load(contacts)
        elif isinstance(contacts, dict):
            # LieLens-compatible dict format
            records = []
            for cid, info in contacts.items():
                emb = info.get("embedding")
                name = info.get("name", cid)
                if emb and len(emb) == 512:
                    records.append(ContactRecord(
                        contact_id=cid,
                        name=name,
                        embedding=emb,
                        company=info.get("company"),
                        role=info.get("role"),
                        last_met=info.get("last_met"),
                        notes=info.get("notes"),
                        email=info.get("email"),
                    ))
            self._index.load(records)


class _AlwaysOn:
    def allow_capture(self) -> bool:
        return True
