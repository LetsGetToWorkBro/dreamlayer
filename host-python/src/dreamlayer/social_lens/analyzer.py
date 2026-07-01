"""social_lens/analyzer.py — SocialLens main orchestrator.

(Formerly FaceRecall — renamed to SocialLens per DreamLayer brand architecture.)

  sl = SocialLens(contacts)
  result = sl.identify(camera_frame)
  card   = result.to_hud_card()
"""
from __future__ import annotations
from typing import Optional
import numpy as np
from .embedder import FaceEmbedder, embed_frame
from .index import ContactIndex
from .enricher import ContactEnricher
from .renderer import SocialLensRenderer
from .schema import ContactRecord, SocialLensResult, MatchResult


class _AlwaysOn:
    def allow_capture(self) -> bool:
        return True


class SocialLens:
    """Personal contacts facial recognition orchestrator.

    Parameters
    ----------
    contacts : list[ContactRecord] or dict
        Personal contacts. Accepts LieLens/TruthLens-compatible dict format.
    threshold : float
        Minimum cosine similarity for a match (default 0.65).
    memory_backend : object, optional
    privacy : object, optional
    """

    def __init__(self, contacts=None, threshold=0.65,
                 memory_backend=None, privacy=None):
        self._embedder = FaceEmbedder(threshold=0.40)
        self._index = ContactIndex(threshold=threshold)
        self._enricher = ContactEnricher(memory_backend)
        self._renderer = SocialLensRenderer()
        self._privacy = privacy or _AlwaysOn()
        if contacts:
            self._load_contacts(contacts)

    def identify(self, frame: Optional[np.ndarray]) -> SocialLensResult:
        if not self._privacy.allow_capture():
            return SocialLensResult(match=None, frame_confidence=0.0, no_face=True)
        embedding, face_conf = embed_frame(frame, self._embedder)
        if embedding is None:
            return SocialLensResult(match=None, frame_confidence=face_conf, no_face=True)
        match = self._index.search(embedding)
        if match is None:
            return SocialLensResult(match=None, frame_confidence=face_conf, no_match=True)
        enriched_contact = self._enricher.enrich(match.contact)
        enriched_match = MatchResult(contact=enriched_contact,
                                     confidence=match.confidence, is_match=True)
        self._enricher.record_encounter(match.contact.contact_id)
        return SocialLensResult(match=enriched_match, frame_confidence=face_conf)

    def add_contact(self, contact: ContactRecord) -> None:
        self._index.add(contact)

    def remove_contact(self, contact_id: str) -> None:
        self._index.remove(contact_id)

    @property
    def contact_count(self) -> int:
        return self._index.size

    def _load_contacts(self, contacts) -> None:
        if isinstance(contacts, list):
            self._index.load(contacts)
        elif isinstance(contacts, dict):
            records = []
            for cid, info in contacts.items():
                emb = info.get("embedding")
                name = info.get("name", cid)
                if emb and len(emb) == 512:
                    records.append(ContactRecord(
                        contact_id=cid, name=name, embedding=emb,
                        company=info.get("company"), role=info.get("role"),
                        last_met=info.get("last_met"), notes=info.get("notes"),
                        email=info.get("email"),
                    ))
            self._index.load(records)
