"""PII redaction middleware (presidio) — "structured meaning, never raw"
enforced before any memory write.

ADD-alongside: new module. Lazy-imports presidio (extras group `privacy`); when
absent it falls back to a conservative regex redactor (emails, phone numbers,
long digit runs). Honors the capture guard: `redact_for_write` refuses (returns
None) when allow_capture() is False.
"""
from __future__ import annotations
import logging
import re

log = logging.getLogger("dreamlayer.pii_presidio")

try:
    from presidio_analyzer import AnalyzerEngine  # type: ignore
    from presidio_anonymizer import AnonymizerEngine  # type: ignore
    _HAS_PRESIDIO = True
except BaseException:  # ImportError, or a broken native dep (pyo3 PanicException)
    _HAS_PRESIDIO = False

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\b(?:\+?\d[\d\-\s().]{7,}\d)\b")
_LONGNUM = re.compile(r"\b\d{6,}\b")


class PiiRedactor:
    available = _HAS_PRESIDIO

    def __init__(self):
        self._analyzer = None
        self._anon = None
        if _HAS_PRESIDIO:
            try:
                self._analyzer = AnalyzerEngine()
                self._anon = AnonymizerEngine()
            except Exception as exc:
                log.warning("[pii] presidio init failed: %s; regex fallback", exc)
                self._analyzer = None

    def redact(self, text: str) -> str:
        if self._analyzer is not None:
            try:
                results = self._analyzer.analyze(text=text, language="en")
                return self._anon.anonymize(text=text, analyzer_results=results).text
            except Exception as exc:
                log.warning("[pii] presidio analyze failed: %s; regex", exc)
        text = _EMAIL.sub("<EMAIL>", text)
        text = _PHONE.sub("<PHONE>", text)
        text = _LONGNUM.sub("<NUM>", text)
        return text

    def redact_for_write(self, text: str, privacy=None) -> str | None:
        """Redact then return the safe string — or None if the veil is down."""
        if privacy is not None and hasattr(privacy, "allow_capture") and not privacy.allow_capture():
            return None
        return self.redact(text)
