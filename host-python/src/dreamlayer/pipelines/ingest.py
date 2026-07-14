"""ingest.py — transcript → memory_events  (three-tier NLP pipeline).

Tier 1  regex/heuristic     zero deps, always runs
Tier 2  spaCy NER           optional, lazy-loaded
Tier 3  GPT-4o-mini         optional, only when needed

Tier 3 is triggered when:
  • Any tier-1/2 event confidence < config.llm_confidence_threshold (0.60)
  • Transcript word count > config.llm_word_threshold (40)
  • Tier 1+2 returned zero events on a non-trivial transcript

Public API
----------
from dreamlayer.pipelines.ingest import IngestPipeline, MemoryEvent

# Without LLM (tier 1+2 only)
pipeline = IngestPipeline(db)

# With LLM (all three tiers)
from dreamlayer.config import CONFIG
pipeline = IngestPipeline.with_llm(db, CONFIG)

events = pipeline.ingest(transcript, context={
    "location": "kitchen",
    "people":   ["Sarah"],
})
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# MemoryEvent
# ---------------------------------------------------------------------------

@dataclass
class MemoryEvent:
    kind:       str
    summary:    str
    confidence: float = 0.7
    source:     str   = "transcript"   # "transcript" | "llm"
    meta:       dict  = field(default_factory=dict)
    db_id:      int   = 0


# ---------------------------------------------------------------------------
# Tier-1 regex/heuristic
# ---------------------------------------------------------------------------

_LOC_PREP = re.compile(
    r"\b(on|in|at|by|near|under|inside|beside|behind|above|below|over|onto)\b",
    re.IGNORECASE,
)
_NP_AFTER = re.compile(
    r"(?:on|in|at|by|near|under|inside|beside|behind|above|below|over|onto)\s+"
    r"(?:the\s+|a\s+|my\s+|your\s+|our\s+)?([a-zA-Z][\w\s]{1,30}?)(?:\.|,|and|but|or|$)",
    re.IGNORECASE,
)
_PROMISE_CUES = re.compile(
    r"\b(i'?ll|i will|i can|i promise|i'?ll send|let me|i'?m going to)\b",
    re.IGNORECASE,
)
_DUE_HINTS = re.compile(
    r"\b(by\s+(?:end of\s+)?(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|next week|eod|tonight|morning|afternoon|evening)|this week|asap)\b",
    re.IGNORECASE,
)
_TASK_CUES = re.compile(
    r"\b(remember to|don'?t forget(?: to)?|need to|have to|gotta|must|make sure(?: to)?|remind me to)\b",
    re.IGNORECASE,
)
_STOPWORDS = frozenset({
    "I", "The", "A", "An", "It", "He", "She", "They", "We", "You",
    "This", "That", "These", "Those", "OK", "Oh", "So", "And", "But",
    "Or", "If", "Then", "When", "Where", "What", "How", "Why",
})
_NAME_RE = re.compile(r"\b([A-Z][a-z]{1,20})(?:\s+[A-Z][a-z]{1,20})?\b")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?]|\n", text) if s.strip()]


def _extract_tier1(text: str, context: dict) -> list[MemoryEvent]:
    events: list[MemoryEvent] = []
    location = (context or {}).get("location", "")
    known_people = {p.lower() for p in (context or {}).get("people", [])}

    for sent in _sentences(text):
        # object + place
        for m in _NP_AFTER.finditer(sent):
            np = m.group(1).strip()
            if len(np) < 2:
                continue
            before = sent[:m.start()].strip()
            obj = " ".join(before.split()[-3:]).strip(" ,;")
            place = f"{np} ({location})" if location else np
            if obj:
                events.append(MemoryEvent(
                    kind="object", summary=f"{obj} → {place}",
                    confidence=0.90,
                    meta={"object": obj, "place": np, "location": location},
                ))
            events.append(MemoryEvent(
                kind="place", summary=place,
                confidence=0.80,
                meta={"place": np, "location": location},
            ))

        # promise
        if _PROMISE_CUES.search(sent):
            recipient = ""
            to_m = re.search(r"\bto\s+([A-Z][a-z]+)", sent)
            if to_m:
                recipient = to_m.group(1)
            else:
                for nm in _NAME_RE.finditer(sent):
                    if nm.group(0) not in _STOPWORDS:
                        recipient = nm.group(0); break
            due = ""
            dm = _DUE_HINTS.search(sent)
            if dm:
                due = dm.group(0).strip()
            pm = _PROMISE_CUES.search(sent)
            task_text = re.sub(r"^to\s+", "", sent[pm.end():].strip().rstrip(".!?,"), flags=re.IGNORECASE) if pm else sent
            summary = f"Promise to {recipient}: {task_text}" if recipient else f"Promise: {task_text}"
            events.append(MemoryEvent(
                kind="promise", summary=summary, confidence=0.85,
                meta={"person": recipient, "task": task_text, "due": due},
            ))

        # task
        tm = _TASK_CUES.search(sent)
        if tm:
            task_text = re.sub(r"^to\s+", "", sent[tm.end():].strip().rstrip(".!?,"), flags=re.IGNORECASE)
            events.append(MemoryEvent(
                kind="task", summary=f"Task: {task_text}",
                confidence=0.70,
                meta={"task": task_text},
            ))

        # person
        for nm in _NAME_RE.finditer(sent):
            name = nm.group(0)
            if name in _STOPWORDS:
                continue
            conf = 0.85 if name.lower() in known_people else 0.75
            events.append(MemoryEvent(
                kind="person", summary=f"Person: {name}",
                confidence=conf,
                meta={"person": name},
            ))

    return events


# ---------------------------------------------------------------------------
# Tier-2 spaCy (optional)
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
    if not _try_load_spacy() or _nlp is None:
        return tier1
    doc = _nlp(text)
    extra: list[MemoryEvent] = []
    known = {e.summary for e in tier1}
    location = (context or {}).get("location", "")
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            s = f"Person: {ent.text}"
            if s not in known:
                extra.append(MemoryEvent(kind="person", summary=s, confidence=0.85, meta={"person": ent.text}))
            else:
                for e in tier1:
                    if e.summary == s:
                        e.confidence = max(e.confidence, 0.85)
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            place = f"{ent.text} ({location})" if location else ent.text
            if place not in known:
                extra.append(MemoryEvent(kind="place", summary=place, confidence=0.80, meta={"place": ent.text, "location": location}))
    return tier1 + extra


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _canonical(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).split().__str__()


def _deduplicate(events: list[MemoryEvent]) -> list[MemoryEvent]:
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
    """Three-tier transcript → memory_events pipeline.

    Parameters
    ----------
    db       : MemoryDB  database to write events into
    use_spacy: bool      attempt spaCy tier-2 (default True)
    llm      : LLMClient | None  GPT-4o-mini tier-3 (default None = disabled)
    llm_confidence_threshold : float
        Trigger tier-3 if any tier-1/2 event confidence is below this. (0.60)
    llm_word_threshold : int
        Trigger tier-3 if transcript word count exceeds this. (40)
    """

    def __init__(
        self,
        db,
        use_spacy: bool = True,
        llm=None,
        llm_confidence_threshold: float = 0.60,
        llm_word_threshold: int = 40,
    ):
        self.db = db
        self.use_spacy = use_spacy
        self.llm = llm
        self.llm_confidence_threshold = llm_confidence_threshold
        self.llm_word_threshold = llm_word_threshold

    @classmethod
    def with_llm(cls, db, config, use_spacy: bool = True) -> "IngestPipeline":
        """Convenience constructor that wires LLMClient from config."""
        from .llm_client import LLMClient
        return cls(
            db=db,
            use_spacy=use_spacy,
            llm=LLMClient(config),
            llm_confidence_threshold=getattr(config, "llm_confidence_threshold", 0.60),
            llm_word_threshold=getattr(config, "llm_word_threshold", 40),
        )

    def _should_use_llm(self, transcript: str, events: list[MemoryEvent]) -> bool:
        """Return True if tier-3 LLM call is warranted."""
        if self.llm is None:
            return False
        word_count = len(transcript.split())
        if word_count > self.llm_word_threshold:
            return True
        if not events and word_count > 4:
            return True
        if any(e.confidence < self.llm_confidence_threshold for e in events):
            return True
        return False

    def ingest(self, transcript: str, context: dict | None = None,
               write_commitments: bool = True) -> list[MemoryEvent]:
        """Extract memory events from *transcript* and persist to DB.

        Parameters
        ----------
        transcript : str   raw speech-to-text or typed input
        context    : dict  optional keys: location, people, timestamp
        write_commitments : bool  when False, `promise` events still persist as
            memories but do NOT also write a commitment row. The caller sets this
            when it has already written the conversation's commitments from a
            more authoritative source (structured turns[].commitment), so one
            promise doesn't land as two commitment rows.

        Returns
        -------
        list[MemoryEvent]  each event has db_id > 0 after DB write
        """
        if not transcript or not transcript.strip():
            return []

        context   = context or {}
        timestamp = context.get("timestamp") or datetime.now(UTC).isoformat()

        # Tier 1
        events = _extract_tier1(transcript, context)

        # Tier 2
        if self.use_spacy:
            events = _extract_tier2_spacy(transcript, context, events)

        # Tier 3
        if self._should_use_llm(transcript, events):
            llm_events = self.llm.extract(transcript, context)
            events = events + llm_events

        # Deduplicate across all tiers
        events = _deduplicate(events)

        # Write to DB
        for ev in events:
            meta = dict(ev.meta)
            meta["timestamp"] = timestamp
            meta["source"]    = ev.source

            if ev.kind == "promise" and write_commitments:
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
