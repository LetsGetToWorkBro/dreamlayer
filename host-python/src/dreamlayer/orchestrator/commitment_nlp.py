"""spaCy commitment extraction — pull (person, action, deadline) tuples from a
line so CommitmentDriftEngine.nudge() gets reliable structure.

ADD-alongside: new module (commitment_drift.py untouched). Lazy-imports spaCy
(extras group `intelligence`); when absent it falls back to a lightweight
regex/keyword extractor, so the tuple surface is populated either way.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("dreamlayer.commitment_nlp")

try:
    import spacy  # type: ignore
    _HAS_SPACY = True
except ImportError:
    _HAS_SPACY = False

_DEADLINE = re.compile(
    r"\b(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|next week|by \w+|in \d+ (?:min|minutes|hours?|days?))\b", re.I)


@dataclass
class Commitment:
    subject: Optional[str]
    action: str
    deadline: Optional[str]


class CommitmentNLP:
    available = _HAS_SPACY

    def __init__(self):
        self._nlp = None
        if _HAS_SPACY:
            try:
                self._nlp = spacy.load("en_core_web_sm")
            except Exception as exc:
                log.warning("[commitment_nlp] model load failed: %s; regex fallback", exc)
                self._nlp = None

    def extract(self, text: str) -> Optional[Commitment]:
        if self._nlp is not None:
            try:
                return self._spacy_extract(text)
            except Exception as exc:
                log.warning("[commitment_nlp] parse failed: %s; regex fallback", exc)
        return self._regex_extract(text)

    def _spacy_extract(self, text) -> Optional[Commitment]:
        doc = self._nlp(text)
        subj = next((e.text for e in doc.ents if e.label_ == "PERSON"), None)
        root = next((t for t in doc if t.dep_ == "ROOT"), None)
        action = (root.lemma_ if root else text).strip()
        dl = next((e.text for e in doc.ents if e.label_ in ("DATE", "TIME")), None)
        if dl is None:
            m = _DEADLINE.search(text)
            dl = m.group(0) if m else None
        return Commitment(subj, action or text, dl)

    def _regex_extract(self, text) -> Optional[Commitment]:
        if not text.strip():
            return None
        m = _DEADLINE.search(text)
        deadline = m.group(0) if m else None
        # crude subject: first Capitalized token that isn't the sentence-initial
        # word (usually a verb like "Send"/"Remind") and isn't part of the deadline
        words = text.split()
        dl_text = (deadline or "").lower()
        subj = None
        for i, w in enumerate(words):
            if i == 0:
                continue
            if re.fullmatch(r"[A-Z][a-z]+", w) and w.lower() not in dl_text:
                subj = w
                break
        return Commitment(subj, text.strip(), deadline)
