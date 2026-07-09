"""spaCy NER for the Social Lens — pull PERSON/ORG entities from a line to feed
introductions and dossiers.

ADD-alongside: new sibling (introduction.py / enricher.py untouched). Lazy-imports
spaCy (extras group `intelligence`); when absent it falls back to a capitalized-
token heuristic, so name extraction still works offline.
"""
from __future__ import annotations
import logging
import re

log = logging.getLogger("dreamlayer.ner_spacy")

try:
    import spacy  # type: ignore
    _HAS_SPACY = True
except ImportError:
    _HAS_SPACY = False

_STOP = {"I", "You", "We", "They", "The", "A", "An", "Hi", "Hey", "Hello", "This", "That"}


class SpacyNER:
    available = _HAS_SPACY

    def __init__(self):
        self._nlp = None
        if _HAS_SPACY:
            try:
                self._nlp = spacy.load("en_core_web_sm")
            except Exception as exc:
                log.warning("[ner_spacy] model load failed: %s; heuristic fallback", exc)
                self._nlp = None

    def people(self, text: str) -> list[str]:
        if self._nlp is not None:
            try:
                return [e.text for e in self._nlp(text).ents if e.label_ == "PERSON"]
            except Exception as exc:
                log.warning("[ner_spacy] parse failed: %s; heuristic", exc)
        return self._heuristic(text)

    def orgs(self, text: str) -> list[str]:
        if self._nlp is not None:
            try:
                return [e.text for e in self._nlp(text).ents if e.label_ == "ORG"]
            except Exception:
                pass
        return []

    @staticmethod
    def _heuristic(text: str) -> list[str]:
        return [w for w in re.findall(r"\b([A-Z][a-z]+)\b", text) if w not in _STOP]
