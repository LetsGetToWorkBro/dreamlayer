"""PII redaction middleware (presidio) — "structured meaning, never raw"
enforced before any memory write.

ADD-alongside: new module. Lazy-imports presidio (extras group `privacy`); when
absent it falls back to a conservative regex redactor (emails, phone numbers,
long digit runs). Honors the capture guard: `redact_for_write` refuses (returns
None) when allow_capture() is False.
"""
from __future__ import annotations
import logging
import os
import re

log = logging.getLogger("dreamlayer.pii_presidio")

# Contact / financial identifiers ONLY — never PERSON, LOCATION, DATE_TIME, NRP.
# The product's whole purpose is remembering people (by name, with consent), so
# scrubbing names would gut recall — "call <PERSON> about the <LOCATION> lease"
# is useless. We strip only the verbatim identifiers a memory never needs to keep
# (a card, an SSN, a phone, an email), leaving the human meaning intact.
_SAFE_ENTITIES = ["PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "US_SSN",
                  "IBAN_CODE", "CRYPTO", "US_BANK_NUMBER", "US_PASSPORT",
                  "US_DRIVER_LICENSE", "MEDICAL_LICENSE", "IP_ADDRESS"]

try:
    import presidio_analyzer  # type: ignore  # noqa: F401 — availability probe; the
    from presidio_anonymizer import AnonymizerEngine  # type: ignore  # engine is built via nlp_setup
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
            # Build the analyzer through nlp_setup so it uses the small
            # en_core_web_sm model `dreamlayer setup models` installs, not
            # presidio's ~560 MB default. Fail-safe: a missing model → None →
            # the regex fallback below (no behaviour change vs. before when the
            # model isn't present; the win is that ONE small download activates it).
            from .. import nlp_setup
            self._analyzer = nlp_setup.analyzer_engine()
            if self._analyzer is not None:
                try:
                    self._anon = AnonymizerEngine()
                except Exception as exc:
                    log.warning("[pii] presidio anonymizer init failed: %s; regex fallback", exc)
                    self._analyzer = None

    def redact(self, text: str) -> str:
        if self._analyzer is not None:
            try:
                # scope presidio to the safe, name-free entity set (above)
                results = self._analyzer.analyze(
                    text=text, language="en", entities=_SAFE_ENTITIES)
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


_REDACTOR: "PiiRedactor | None" = None
_REDACTOR_BUILT = False


def default_redactor() -> "PiiRedactor | None":
    """The write-path PII scrubber the memory store applies to every summary
    before it's stored — or None when the pii_redaction capability is toggled off
    (DL_DISABLE_PII_REDACTION, which the panel's per-cap switch now sets). Built
    once and memoized. Uses presidio's narrow entity set when installed, else the
    regex fallback (emails/phones/long numbers), so scrubbing is ALWAYS on by
    default (a strict privacy improvement over the prior state, where nothing on
    the write path redacted at all) yet fully switch-off-able."""
    global _REDACTOR, _REDACTOR_BUILT
    if str(os.environ.get("DL_DISABLE_PII_REDACTION", "")).strip().lower() \
            in ("1", "true", "yes", "on"):
        return None
    if not _REDACTOR_BUILT:
        _REDACTOR_BUILT = True
        try:
            _REDACTOR = PiiRedactor()
        except Exception as exc:                 # never let PII init break a write
            log.warning("[pii] redactor init failed: %s; writes unredacted", exc)
            _REDACTOR = None
    return _REDACTOR
