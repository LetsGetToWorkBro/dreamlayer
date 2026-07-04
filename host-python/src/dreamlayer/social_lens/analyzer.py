"""social_lens/analyzer.py — SocialLens main orchestrator.

The single entry point. Called on double-tap (IMU trigger) from the
orchestrator or Dream Engine.

  fr = SocialLens(contacts)
  result = fr.identify(camera_frame)   # synchronous, < 30ms on-device
  card   = result.to_hud_card()        # send to HUD renderer

Pipeline
--------
  Stage 1  embed_frame()      → 512-d embedding + face confidence
  Stage 2  index.search()     → MatchResult or None
  Stage 3  enricher.enrich()  → ContactRecord with last-met + notes
  Stage 4  renderer.render()  → SocialLensCard dict
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
from .introduction import IntroductionCapture
from .renderer import SocialLensRenderer
from .schema import ContactRecord, SocialLensResult, MatchResult


class SocialLens:
    """Personal contacts facial recognition orchestrator.

    Parameters
    ----------
    contacts : list[ContactRecord] or dict, optional
        Personal contacts to match against.
        - list[ContactRecord]: loaded directly
        - dict: {contact_id: {"name": str, "embedding": list, ...}}
          (compatible with TruthLens contact_registry format)
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
        auto_keep_introductions: bool = True,
    ):
        self._embedder = FaceEmbedder(threshold=0.40)
        self._index = ContactIndex(threshold=threshold)
        self._enricher = ContactEnricher(memory_backend)
        self._renderer = SocialLensRenderer()

        self._privacy = privacy or _AlwaysOn()

        # Name-you-were-told capture shares this instance's index,
        # enricher, embedder, and privacy gate, so a kept introduction
        # is recallable by the very next identify(). auto_keep (the
        # default) saves a heard self-introduction immediately;
        # auto_keep_introductions=False restores the offer/confirm flow.
        self.introductions = IntroductionCapture(
            index=self._index,
            enricher=self._enricher,
            privacy=self._privacy,
            embedder=self._embedder,
            auto_keep=auto_keep_introductions,
        )

        # the last face recall — so "remember she's into climbing" can attach
        # to whoever you were just looking at (set on every match)
        self._last_identified: Optional[str] = None

        if contacts:
            self._load_contacts(contacts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def identify(self, frame: Optional[np.ndarray]) -> SocialLensResult:
        """Identify a person from a camera frame.

        Always returns a SocialLensResult — never raises.
        Check result.no_face / result.no_match / result.match.
        """
        if not self._privacy.allow_capture():
            return SocialLensResult(match=None, frame_confidence=0.0,
                                    no_face=True)

        # Stage 1: embed
        embedding, face_conf = embed_frame(frame, self._embedder)
        if embedding is None:
            return SocialLensResult(match=None,
                                    frame_confidence=face_conf,
                                    no_face=True)

        # Stage 2: search
        match = self._index.search(embedding)
        if match is None:
            return SocialLensResult(match=None,
                                    frame_confidence=face_conf,
                                    no_match=True)

        # Stage 3: enrich
        enriched_contact = self._enricher.enrich(match.contact)
        enriched_match = MatchResult(
            contact=enriched_contact,
            confidence=match.confidence,
            is_match=True,
        )

        # Stage 5: record encounter (update last-met) + remember who this was
        self._enricher.record_encounter(match.contact.contact_id)
        self._last_identified = match.contact.contact_id

        return SocialLensResult(
            match=enriched_match,
            frame_confidence=face_conf,
        )

    def offer_introduction(self, utterance: str, frame=None,
                           now=None) -> Optional[dict]:
        """Hear a spoken self-introduction.

        With auto_keep (the default) the name is saved immediately and
        the KeptCard is returned. With auto_keep_introductions=False this
        returns an offer card and saves nothing until
        confirm_introduction(). Returns None when nothing was recognised
        or the veil is down.
        """
        return self.introductions.heard(utterance, frame=frame, now=now)

    def confirm_introduction(self, **extra) -> Optional[ContactRecord]:
        """Keep the currently offered name (consent flow only)."""
        return self.introductions.confirm(**extra)

    def dismiss_introduction(self) -> None:
        """Let the current offer go, unremembered."""
        self.introductions.dismiss()

    def add_note(self, note: str, who: Optional[str] = None):
        """Jot a note about a person, on the spot. `who` is a name; omit it to
        note whoever you just looked at (the last identify() match). The note is
        appended to that contact's own record — it shows on the recall card the
        next time you see them. Returns the ContactRecord it landed on, or None
        if the person couldn't be resolved (unknown name / nobody in view)."""
        contact = None
        if who:
            contact = self._index.find_by_name(who)
        elif self._last_identified:
            contact = self._index.get(self._last_identified)
        if contact is None:
            return None
        self._enricher.append_note(contact.contact_id, note)
        return self._enricher.enrich(contact)

    def meet(self, name: str, frame=None, note: Optional[str] = None,
             relation: Optional[str] = None):
        """Meet someone on the spot — "this is Sarah" while looking at them.
        If a contact by that name already exists, the note/relation is added to
        them; otherwise a new contact is created from the face in view (or
        name-only if no face). Sets last_identified so a follow-up "remember
        she…" attaches. Returns the enriched record, or None (veiled / no name)."""
        if not name:
            return None
        existing = self._index.find_by_name(name)
        if existing is not None:
            if relation:
                self._enricher.set_relation(existing.contact_id, relation)
            if note:
                self._enricher.append_note(existing.contact_id, note)
            self._last_identified = existing.contact_id
            return self._enricher.enrich(existing)
        record = self.introductions.enroll(name, frame=frame, note=note)
        if record is None:
            return None                       # veiled
        if relation:
            self._enricher.set_relation(record.contact_id, relation)
        self._last_identified = record.contact_id
        return self._enricher.enrich(record)

    def add_debt(self, direction: str, what: str, who: Optional[str] = None):
        """Track a debt/favor with a person — by name, or (who=None) whoever you
        just looked at. Returns the enriched record, or None if unresolved."""
        contact = self._index.find_by_name(who) if who else (
            self._index.get(self._last_identified) if self._last_identified else None)
        if contact is None:
            return None
        self._enricher.add_debt(contact.contact_id, direction, what)
        return self._enricher.enrich(contact)

    def add_debt_by_id(self, contact_id: str, direction: str, what: str):
        self._enricher.add_debt(contact_id, direction, what)
        contact = self._index.get(contact_id)
        return self._enricher.enrich(contact) if contact is not None else None

    def settle(self, who: Optional[str] = None):
        """Clear all debts with a person (settled up). Returns the record."""
        contact = self._index.find_by_name(who) if who else (
            self._index.get(self._last_identified) if self._last_identified else None)
        if contact is None:
            return None
        self._enricher.clear_debts(contact.contact_id)
        return self._enricher.enrich(contact)

    def settle_by_id(self, contact_id: str) -> None:
        self._enricher.clear_debts(contact_id)

    def add_note_by_id(self, contact_id: str, note: str):
        """Append a note to a specific contact_id (the caller already resolved
        who you were looking at). The enricher stores notes by id whether or not
        a face is in the recall index, so name-only contacts get notes too.
        Returns the enriched record when the contact is in the index, else None
        (the note is still stored)."""
        self._enricher.append_note(contact_id, note)
        contact = self._index.get(contact_id)
        return self._enricher.enrich(contact) if contact is not None else None

    @property
    def last_identified(self) -> Optional[str]:
        """contact_id of the person most recently recalled, or None."""
        return self._last_identified

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
            # TruthLens-compatible dict format
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
