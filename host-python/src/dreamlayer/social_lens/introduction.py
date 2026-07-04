"""social_lens/introduction.py — name-you-were-told capture.

The self-introduction counterpart to face recall. Social Lens never
looks a stranger up. But when someone introduces themselves *out loud*
— "Hi, I'm Maya" — you were told their name, to your face, on purpose.
This module keeps that name in your *own* memory, and nothing else.

The discipline, end to end:

  automatic   By default (auto_keep=True) a heard self-introduction is
              kept immediately — the way a person keeps a name they were
              just given — and the KeptCard states the saved fact. With
              auto_keep=False the older consent flow runs instead:
              hearing only *offers*, nothing is saved until a deliberate
              confirm, and an unconfirmed offer expires (OFFER_TTL_S).
  spoken      Only a closed, offline grammar of self-introductions
              ("my name is …", "I'm …", "this is …", "call me …") ever
              captures anything. Ambient chatter produces nothing —
              this is what keeps the boundary at people who chose to
              give you their name, never bystanders.
  in-place    The name — and the face in front of you — is written to
              your local contacts. No lookup, no database, no network.
              Ever.
  veiled      While Privacy Veil is paused, the ear is closed too: a
              heard name during the veil is neither kept nor offered and
              grabs no face. Silence means silence.

A kept introduction becomes a normal ContactRecord, so the very next
time that face appears, ordinary Social Lens recall says the name back
to you — and the conversation ledger grows its dossier from there.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .embedder import FaceEmbedder, embed_frame
from .schema import ContactRecord

OFFER_TTL_S = 12.0        # an un-confirmed offer forgets itself
MAX_NAME_WORDS = 3        # "Maya", "Maya Chen", "Maria del Carmen"

# Closed grammar, two kinds of trigger:
#   explicit — the phrase itself declares "a name follows", so whatever
#              comes next is taken as the name even in an all-lowercase
#              transcription ("my name is maria del carmen").
#   soft     — conversational openers that only *sometimes* precede a
#              name, so the following token must be capitalised in the
#              source to count. This is what lets "I'm Maya" through
#              while "I'm running late" and "I'm sorry" fall out, with no
#              brittle list of non-name words to maintain.
# Longer phrases are tried first so they win over their own prefixes.
_EXPLICIT = ("my name is", "my name's", "the name's", "call me")
_SOFT = ("i am", "i'm", "im", "this is", "that's")

# Lower-case connectors that stay part of a multiword name.
_CONNECTORS = frozenset({"del", "van", "de", "la", "der", "bin", "von", "di"})

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def _find_trigger(low: str):
    """Earliest trigger in the utterance, preferring longer matches.

    Returns (end_index, is_explicit) or None.
    """
    best = None                                  # (start, end, explicit)
    for explicit, group in ((True, _EXPLICIT), (False, _SOFT)):
        for trig in group:
            m = re.search(r"\b" + re.escape(trig) + r"\b", low)
            if m is None:
                continue
            if best is None or m.start() < best[0] or (
                    m.start() == best[0] and m.end() > best[1]):
                best = (m.start(), m.end(), explicit)
    if best is None:
        return None
    return best[1], best[2]


def parse_introduction(utterance: Optional[str]) -> Optional[str]:
    """Return the introduced name from a self-introduction, else None.

    Deterministic, offline, closed-grammar. Recognises only the shapes a
    person actually uses to give you their name, and refuses everything
    else — including "nice to meet you", which names no one.
    """
    if not utterance:
        return None
    found = _find_trigger(utterance.lower())
    if found is None:
        return None
    end, explicit = found

    words = _WORD.findall(utterance[end:])
    name_words: list[str] = []
    prev_connector = False
    for w in words:
        if not name_words:
            # First word after the trigger. A soft trigger demands a
            # capitalised token; an explicit trigger takes it as given.
            if not explicit and not w[0].isupper():
                return None
            name_words.append(w)
            prev_connector = w.lower() in _CONNECTORS
            continue
        if len(name_words) >= MAX_NAME_WORDS:
            break
        # Continue the name through capitalised words, known connectors,
        # and the single word that follows a connector; stop at the first
        # ordinary word ("Maya and I..." -> "Maya").
        wl = w.lower()
        if w[0].isupper() or wl in _CONNECTORS or prev_connector:
            name_words.append(w)
            prev_connector = wl in _CONNECTORS
        else:
            break
    if not name_words:
        return None
    name = " ".join(name_words).strip("'-")
    # Title-case an all-lower-case transcription ("maya" -> "Maya"); leave
    # already-cased names ("Maya Chen") as the speaker's casing.
    if name and name == name.lower():
        name = name.title()
    return name or None


@dataclass
class IntroductionOffer:
    """A staged, unconfirmed offer to remember a spoken name.

    Holds the face embedding captured in the moment (when a frame was
    present and the veil was open) so that confirming enrols a contact
    who is recallable by face next time. No embedding → a name-only
    memory, still yours, just not a face match.
    """
    name: str
    heard_ts: float
    embedding: Optional[list[float]] = None
    face_confidence: float = 0.0
    contact_id: str = ""

    def __post_init__(self):
        if not self.contact_id:
            seed = f"{self.name}|{self.heard_ts:.3f}".encode()
            self.contact_id = "intro_" + hashlib.sha256(seed).hexdigest()[:12]

    def has_face(self) -> bool:
        return self.embedding is not None

    def to_hud_card(self) -> dict:
        """The offer card. It asks; it never states a saved fact."""
        detail = ("double-tap to remember  •  dismiss to skip"
                  if self.has_face()
                  else "name only — no face in view")
        return {
            "type": "IntroOfferCard",
            "dismiss_ms": int(OFFER_TTL_S * 1000),
            "eyebrow": "REMEMBER THEM?",
            "primary": self.name,
            "detail": detail,
            "footer": "stays on your device",
            "color": 0x5EF7,
            "opacity": 0.9,
            "has_face": self.has_face(),
            "contact_id": self.contact_id,
            "lines": ["REMEMBER THEM?", self.name, detail],
        }

    def to_kept_card(self) -> dict:
        """The kept card (auto_keep). It states the saved fact."""
        detail = ("introduced themselves — kept"
                  if self.has_face()
                  else "name only — no face in view")
        return {
            "type": "IntroKeptCard",
            "dismiss_ms": 5000,
            "eyebrow": "KEPT",
            "primary": self.name,
            "detail": detail,
            "footer": "on your device · veil silences this",
            "color": 0x5EF7,
            "opacity": 0.9,
            "has_face": self.has_face(),
            "contact_id": self.contact_id,
            "lines": ["KEPT", self.name, detail],
        }


class IntroductionCapture:
    """Turns a name you were told into a contact of your own.

    Parameters
    ----------
    index : ContactIndex-like, optional
        Where a kept face-bearing introduction is enrolled (so the
        SocialLens recall path finds it next time). Usually a live
        SocialLens' internal index, supplied via SocialLens.introductions.
    enricher : ContactEnricher-like, optional
        Where the "met today" stamp and any name-only memory land.
    privacy : object, optional
        Privacy controller with allow_capture() -> bool. When it denies,
        the ear is closed: heard() returns None and grabs no face.
    embedder : FaceEmbedder, optional
        Shared embedder for the in-the-moment face.
    auto_keep : bool
        When True (the default), a heard self-introduction is kept
        immediately and heard() returns the KeptCard. When False, the
        consent flow runs: heard() stages an offer that confirm() /
        dismiss() decide and that expires on its own.
    """

    def __init__(self, index=None, enricher=None, privacy=None,
                 embedder: Optional[FaceEmbedder] = None, now_fn=None,
                 auto_keep: bool = True):
        self._index = index
        self._enricher = enricher
        self._privacy = privacy or _AlwaysOn()
        self._embedder = embedder
        self._now = now_fn or time.time
        self.auto_keep = auto_keep
        self._pending: Optional[IntroductionOffer] = None

    # -- hearing ---------------------------------------------------------

    def heard(self, utterance: str,
              frame: Optional[np.ndarray] = None,
              now: Optional[float] = None) -> Optional[dict]:
        """React to a name spoken in a self-introduction.

        auto_keep on (default): the name is saved immediately and the
        KeptCard is returned — the card states the saved fact.
        auto_keep off: nothing is saved; an offer card is returned that
        confirm() can act on and that expires on its own.
        Returns None when no self-introduction was recognised, and always
        when the veil is down.
        """
        if not self._privacy.allow_capture():
            return None                      # veiled: the ear is closed
        name = parse_introduction(utterance)
        if name is None:
            return None

        now = now if now is not None else self._now()
        embedding: Optional[list[float]] = None
        face_conf = 0.0
        if frame is not None:
            embedding, face_conf = embed_frame(frame, self._embedder)

        offer = IntroductionOffer(
            name=name, heard_ts=now,
            embedding=embedding, face_confidence=face_conf)
        if self.auto_keep:
            self._pending = None
            self._save(offer)
            return offer.to_kept_card()
        self._pending = offer
        return self._pending.to_hud_card()

    # -- deciding --------------------------------------------------------

    @property
    def pending(self) -> Optional[IntroductionOffer]:
        return self._pending

    def confirm(self, now: Optional[float] = None,
                **extra) -> Optional[ContactRecord]:
        """Keep the currently offered name. Returns the saved record.

        The consent-flow (auto_keep=False) counterpart to heard():
        nothing is saved unless there is a live, un-expired offer.
        Optional keyword fields (company, role, notes, email) ride along.
        Under auto_keep the save already happened in heard(), so there is
        no pending offer and this returns None.
        """
        now = now if now is not None else self._now()
        offer = self._take_fresh(now)
        if offer is None:
            return None
        return self._save(offer, **extra)

    def _save(self, offer: IntroductionOffer, **extra) -> ContactRecord:
        """Write an introduction to your own contacts. The only writer."""
        record = ContactRecord(
            contact_id=offer.contact_id,
            name=offer.name,
            embedding=offer.embedding if offer.has_face()
            else [0.0] * 512,
            company=extra.get("company"),
            role=extra.get("role"),
            last_met=extra.get("last_met"),
            notes=extra.get("notes"),
            email=extra.get("email"),
        )
        # Only a real face joins the recall index; a name-only memory
        # must never masquerade as a matchable face (its zero embedding
        # would false-match). It lives as a note instead.
        if offer.has_face() and self._index is not None:
            self._index.add(record)
        if self._enricher is not None:
            self._enricher.record_encounter(record.contact_id)
            if not offer.has_face():
                self._enricher.set_notes(
                    record.contact_id,
                    f"Introduced themselves — name only ({offer.name}).")
        return record

    def dismiss(self) -> None:
        """Let the offer go, unremembered."""
        self._pending = None

    def tick(self, now: Optional[float] = None) -> None:
        """Expire a stale, unconfirmed offer."""
        now = now if now is not None else self._now()
        if self._pending is not None and (
                now - self._pending.heard_ts) > OFFER_TTL_S:
            self._pending = None

    # -- internal --------------------------------------------------------

    def _take_fresh(self, now: float) -> Optional[IntroductionOffer]:
        offer = self._pending
        self._pending = None
        if offer is None:
            return None
        if (now - offer.heard_ts) > OFFER_TTL_S:
            return None                      # expired between hearing and act
        return offer


class _AlwaysOn:
    def allow_capture(self) -> bool:
        return True
