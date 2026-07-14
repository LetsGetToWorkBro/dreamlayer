"""rosetta.py — Rosetta Lens: understand any language.

Two halves, one banner:
  the ear   — live voice translation (Puente, orchestrator/puente_bridge.py):
              real-time captions of what someone is *saying*.
  the eye   — this module: text you *look at* (a menu, a sign) → its meaning.

The eye half is a clean seam: a translation model plugs in via `translate_fn`
(on-device, or the AI brain). With none wired it's a no-op that returns the
source, so the pipeline runs; a real model makes it useful. Source-language
detection is a light offline heuristic (shared vocabulary with Puente).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.rosetta")

# tiny function-word markers per language — enough to guess the source
_MARKERS = {
    "es": {"el", "la", "los", "las", "un", "una", "es", "de", "por", "para",
           "con", "que", "no", "y", "en", "hola", "gracias"},
    "fr": {"le", "la", "les", "un", "une", "de", "des", "et", "est", "pour",
           "avec", "que", "ne", "bonjour", "merci", "vous"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "für", "ein",
           "eine", "danke", "hallo", "ich"},
    "it": {"il", "lo", "la", "un", "una", "di", "che", "per", "con", "non",
           "ciao", "grazie", "sono"},
}


# Non-Latin scripts: a single character in one of these ranges is decisive —
# the text plainly isn't English, so it must NOT fall through to "en" (which
# no-ops the translation). Ordered so kana/hangul win over the shared CJK block.
# (audit 2026-07-14: the old detector only knew es/fr/de/it, so every non-Latin
# sign/menu was misread as English and never translated.)
_SCRIPT_RANGES = (
    ("ja", ((0x3040, 0x30FF),)),                     # hiragana + katakana
    ("ko", ((0xAC00, 0xD7AF), (0x1100, 0x11FF))),    # hangul
    ("zh", ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))),    # CJK ideographs
    ("ar", ((0x0600, 0x06FF), (0x0750, 0x077F))),    # arabic
    ("ru", ((0x0400, 0x04FF),)),                     # cyrillic
    ("hi", ((0x0900, 0x097F),)),                     # devanagari
    ("el", ((0x0370, 0x03FF),)),                     # greek
    ("he", ((0x0590, 0x05FF),)),                     # hebrew
)


def _script_language(text: str) -> Optional[str]:
    for ch in text or "":
        cp = ord(ch)
        for lang, ranges in _SCRIPT_RANGES:
            if any(lo <= cp <= hi for lo, hi in ranges):
                return lang
    return None


def detect_language(text: str) -> str:
    # a non-Latin script is decisive and cheap — check it first
    script = _script_language(text)
    if script is not None:
        return script
    words = set(re.findall(r"[a-zà-ÿ']+", (text or "").lower()))
    best, best_hits = "en", 0
    for lang, markers in _MARKERS.items():
        hits = len(words & markers)
        if hits > best_hits:
            best, best_hits = lang, hits
    return best if best_hits >= 1 else "en"


@dataclass
class RosettaResult:
    source_text: str
    translated: str
    source_lang: str
    target_lang: str
    engine: str = "none"        # which translator produced it

    def changed(self) -> bool:
        return self.translated.strip() != self.source_text.strip()


class RosettaLens:
    """Translate text you look at. Puente handles the voice half."""

    def __init__(self, translate_fn: Optional[Callable[[str, str], str]] = None,
                 detect_fn: Optional[Callable[[str], str]] = None,
                 engine: str = "seam"):
        self._translate = translate_fn
        self._detect = detect_fn or detect_language
        self._engine = engine

    def read(self, text: str, target: str = "en") -> RosettaResult:
        src = self._detect(text)
        if src == target or not text.strip():
            return RosettaResult(text, text, src, target, engine="none")
        if self._translate is None:
            # no model wired: pass the source through (pipeline still runs)
            return RosettaResult(text, text, src, target, engine="none")
        try:
            out = self._translate(text, target)
        except Exception as exc:
            # a failing injected translator degrades to passthrough — but with an
            # observability hook, not silently (audit 2026-07-14).
            log.warning("[rosetta] translate failed (%s→%s): %s", src, target, exc)
            return RosettaResult(text, text, src, target, engine="error")
        return RosettaResult(text, out or text, src, target, engine=self._engine)
