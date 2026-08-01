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
        """Names in `text` — never fewer than the offline heuristic finds (#557).

        `en_core_web_sm` tags no PERSON at all in an ordinary introduction:

            "Hi I'm Priya from Overpass Studio"
              ents           → [('Overpass Studio', 'ORG')]
              people()       → []            (installed)
              _heuristic()   → ['Priya', …]  (absent)

        So installing the optional extra made Name Capture stop capturing the
        name — the offline path answered and the "better" one did not. An empty
        list is not an exception, so the `except` branch never fired.

        When the model DOES name someone it is still trusted outright: it merges
        multi-token names ("Marcus Chen") that the capitalized-token heuristic
        splits in two. The fallback is consulted only when the model found
        nobody — and then the entities it DID find are subtracted, so the
        heuristic's over-capture is filtered by the model's own knowledge rather
        than handed back raw: "Overpass"/"Studio" are dropped because the model
        positively labelled that span ORG, leaving ['Priya'].
        """
        if self._nlp is not None:
            try:
                doc = self._nlp(text)
                found = [e.text for e in doc.ents if e.label_ == "PERSON"]
                if found:
                    return found
                not_people = {tok for e in doc.ents if e.label_ != "PERSON"
                              for tok in e.text.split()}
                return [w for w in self._heuristic(text) if w not in not_people]
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
