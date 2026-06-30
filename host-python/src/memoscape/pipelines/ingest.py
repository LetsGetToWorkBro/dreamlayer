"""ingest.py — transcript → memory_events NLP extraction pipeline.

Two-tier extraction:
  Tier 1: regex/heuristic  (zero deps, always runs)
  Tier 2: spaCy NER        (optional, imported lazily)

Public API
----------
from memoscape.pipelines.ingest import IngestPipeline, MemoryEvent

pipeline = IngestPipeline(db)          # db: MemoryDB instance
events   = pipeline.ingest(transcript) # list[MemoryEvent]
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

# ---------------------------------------------------------------------------
# MemoryEvent dataclass  (what callers get back)
# ---------------------------------------------------------------------------

@dataclass
class MemoryEvent:
    kind:       str                      # "object" | "person" | "place" | "promise" | "task"
    summary:    str                      # human-readable one-liner
    confidence: float = 0.7
    source:     str   = "transcript"
    meta:       dict  = field(default_factory=dict)
    db_id:      int   = 0                # set after DB write


# ---------------------------------------------------------------------------
# Tier-1: regex / heuristic extraction
# ---------------------------------------------------------------------------

# Location prepositions that introduce object-place pairs
_LOC_PREP = re.compile(
    r"\b(on|in|at|by|near|under|inside|beside|behind|above|below|over|onto)\b",
    re.IGNORECASE,
)

# Noun-phrase capture after a preposition (greedy up to punctuation/conjunction)
_NP_AFTER = re.compile(
    r"(?:on|in|at|by|near|under|inside|beside|behind|above|below|over|onto)\s+"
    r"(?:the\s+|a\s+|my\s+|your\s+|our\s+)?([a-zA-Z][\w\s]{1,30}?)(?:\.|,|and|but|or|$)",
    re.IGNORECASE,
)

# Commitment cues
_PROMISE_CUES = re.compile(
    r"\b(i'?ll|i will|i can|i promise|i'?ll send|let me|i'?m going to)\b",
    re.IGNORECASE,
)

# Due-date hints
_DUE_HINTS = re.compile(
    r"\b(by\s+(?:end of\s+)?(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|next week|eod|tonight|morning|afternoon|evening)|this week|asap)\b",
    re.IGNORECASE,
)

# Task imperative cues
_TASK_CUES = re.compile(
    r"\b(remember to|don'?t forget(?: to)?|need to|have to|gotta|must|make sure(?: to)?|remind me to)\b",
    re.IGNORECASE,
)

# Person: capitalised token(s) — very simple NER fallback
_STOPWORDS = frozenset({
    "I", "The", "A", "An", "It", "He", "She", "They", "We", "You",
    "This", "That", "These", "Those", "OK", "Oh", "So", "And", "But",
    "Or", "If", "Then", "When", "Where", "What", "How", "Why",
})
_NAME_RE = re.compile(r"\b([A-Z][a-z]{1,20})(?:\s+[A-Z][a-z]{1,20})?\b")


def _sentences(text: str) -> list[str]:
    """Split on sentence boundaries; tolerate lack of punctuation."""
    return [s.strip() for s in re.split(r"[.!?]|\n", text) if s.strip()]


def _extract_tier1(text: str, context: dict) -> list[MemoryEvent]:
    events: list[MemoryEvent] = []
    sentences = _sentences(text)
    location = (context or {}).get("location", "")
    known_people = {p.lower() for p in (context or {}).get("people", [])}

    for sent in sentences:
        sent_lower = sent.lower()

        # --- object + place ---
        for m in _NP_AFTER.finditer(sent):
            np = m.group(1).strip().rstrip()
            if len(np) < 2:
                continue
            # Try to find what object we're talking about (word(s) before the prep)
            prep_start = m.start()
            before = sent[:prep_start].strip()
            # Last 1-3 words before the preposition as the object
            obj_tokens = before.split()[-3:]
            obj = " ".join(obj_tokens).strip(" ,;")
            place = np
            if location:
                place = f"{np} ({location})"
            if obj:
                summary = f"{obj} → {place}"
                events.append(MemoryEvent(
                    kind="object",
                    summary=summary,
                    confidence=0.90,
                    meta={"object": obj, "place": np, "location": location},
                ))
            # Also record the place itself
            events.append(MemoryEvent(
                kind="place",
                summary=place,
                confidence=0.80,
                meta={"place": np, "location": location},
            ))

        # --- promise / commitment ---
        if _PROMISE_CUES.search(sent):
            # Extract recipient: word after "to" or known person name
            recipient = ""
            to_match = re.search(r"\bto\s+([A-Z][a-z]+)", sent)
            if to_match:
                recipient = to_match.group(1)
            else:
                for m in _NAME_RE.finditer(sent):
                    name = m.group(0)
                    if name not in _STOPWORDS:
                        recipient = name
                        break

            # Extract due date
            due = ""
            dm = _DUE_HINTS.search(sent)
            if dm:
                due = dm.group(0).strip()

            # Task = everything after the promise cue
            pm = _PROMISE_CUES.search(sent)
            task_text = sent[pm.end():].strip().rstrip(".!?,") if pm else sent
            # Strip leading "to "
            task_text = re.sub(r"^to\s+", "", task_text, flags=re.IGNORECASE)

            summary = f"Promise to {recipient}: {task_text}" if recipient else f"Promise: {task_text}"
            events.append(MemoryEvent(
                kind="promise",
                summary=summary,
                confidence=0.85,
                meta={"person": recipient, "task": task_text, "due": due},
            ))

        # --- task ---
        tm = _TASK_CUES.search(sent)
        if tm:
            task_text = sent[tm.end():].strip().rstrip(".!?,")
            task_text = re.sub(r"^to\s+", "", task_text, flags=re.IGNORECASE)
            events.append(MemoryEvent(
                kind="task",
                summary=f"Task: {task_text}",
                confidence=0.70,
                meta={"task": task_text},
            ))

        # --- person ---
        for m in _NAME_RE.finditer(sent):
            name = m.group(0)
            if name in _STOPWORDS:
                continue
            # Skip if already captured as promise recipient in this sentence
            conf = 0.85 if name.lower() in known_people else 0.75
            events.append(MemoryEvent(
                kind="person",
                summary=f"Person: {name}",
                confidence=conf,
                meta={"person": name},
            ))

    return events


# ---------------------------------------------------------------------------
# Tier-2: spaCy NER (optional)
# ---------------------------------------------------------------------------

_nlp = None
_spacy_available = False

def _try_load_spacy():
    global _nlp, _spacy_available
    if _spacy_available:
        return True
    try:
        import spacy  # type: ignore
        _nlp = spacy.load("en_core_web_sm")
        _spacy_available = True
    except Exception:
        _spacy_available = False
    return _spacy_available


def _extract_tier2_spacy(text: str, context: dict, tier1: list[MemoryEvent]) -> list[MemoryEvent]:
    """Augment tier1 with spaCy NER. Returns merged list."""
    if not _try_load_spacy() or _nlp is None:
        return tier1

    doc = _nlp(text)
    extra: list[MemoryEvent] = []
    known_summaries = {e.summary for e in tier1}
    location = (context or {}).get("location", "")

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            summary = f"Person: {ent.text}"
            if summary not in known_summaries:
                extra.append(MemoryEvent(
                    kind="person",
                    summary=summary,
                    confidence=0.85,
                    meta={"person": ent.text},
                ))
            else:
                # Boost confidence of existing person event
                for e in tier1:
                    if e.summary == summary:
                        e.confidence = max(e.confidence, 0.85)
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            place = ent.text
            if location:
                place = f"{ent.text} ({location})"
            summary = place
            if summary not in known_summaries:
                extra.append(MemoryEvent(
                    kind="place",
                    summary=summary,
                    confidence=0.80,
                    meta={"place": ent.text, "location": location},
                ))

    return tier1 + extra


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _canonical(text: str) -> str:
    """Lower-case, collapse whitespace, strip punctuation for fuzzy match."""
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).split().__str__()


def _deduplicate(events: list[MemoryEvent]) -> list[MemoryEvent]:
    """Remove events with identical (kind, canonical summary)."""
    seen: set[tuple[str, str]] = set()
    out: list[MemoryEvent] = []
    for e in events:
        key = (e.kind, _canonical(e.summary))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# IngestPipeline
# ---------------------------------------------------------------------------

class IngestPipeline:
    """Wraps the two-tier extractor and writes results to MemoryDB.

    Parameters
    ----------
    db : MemoryDB
        The database instance to write to.
    use_spacy : bool
        If True (default), attempt to load spaCy tier-2. Falls back silently.
    """

    def __init__(self, db, use_spacy: bool = True):
        self.db = db
        self.use_spacy = use_spacy

    def ingest(self, transcript: str, context: dict | None = None) -> list[MemoryEvent]:
        """Extract memory events from *transcript* and persist to DB.

        Parameters
        ----------
        transcript : str
            Raw speech-to-text or typed input.
        context : dict, optional
            Keys:
              ``location``  (str)  current place name
              ``people``    (list[str])  known contacts in session
              ``timestamp`` (str)  ISO-8601 override (defaults to now)

        Returns
        -------
        list[MemoryEvent]
            Each event has ``db_id > 0`` after successful DB write.
        """
        if not transcript or not transcript.strip():
            return []

        context = context or {}
        timestamp = context.get("timestamp") or datetime.now(UTC).isoformat()

        # Tier-1 extraction
        events = _extract_tier1(transcript, context)

        # Tier-2 spaCy augmentation
        if self.use_spacy:
            events = _extract_tier2_spacy(transcript, context, events)

        # Deduplicate within this batch
        events = _deduplicate(events)

        # Write to DB
        for ev in events:
            meta = dict(ev.meta)
            meta["timestamp"] = timestamp
            meta["source"] = "transcript"

            if ev.kind == "promise":
                # Commitments go to the commitments table too
                self.db.add_commitment(
                    person=ev.meta.get("person", ""),
                    task=ev.meta.get("task", ev.summary),
                    due=ev.meta.get("due", ""),
                    confidence=ev.confidence,
                )

            ev.db_id = self.db.add_memory(
                kind=ev.kind,
                summary=ev.summary,
                confidence=ev.confidence,
                meta=meta,
            )

        return events
