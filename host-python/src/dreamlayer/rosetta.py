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

import re
from dataclasses import dataclass
from typing import Callable, Optional

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


def detect_language(text: str) -> str:
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
        except Exception:
            return RosettaResult(text, text, src, target, engine="error")
        return RosettaResult(text, out or text, src, target, engine=self._engine)
