"""app/puente_bridge.py

PuenteBridge — Puente live-caption → DreamLayer LiveCaptionCard pipeline.

Puente produces real-time Spanish-English (and English-Spanish) caption
events.  This module receives those events, normalises the payload, and
produces LiveCaptionCard dicts ready for BLE dispatch to the glasses.

Architecture
------------
    puente_feed  →  PuenteBridge.on_caption()  →  LiveCaptionCard dict
                                                →  registered card callbacks

Puente integration is callback-based and has no external deps inside this
module: the caller injects the caption text + metadata.  Puente's actual
transport (WebSocket / gRPC / BLE) stays outside this boundary.

Language detection
------------------
If the caller does not supply `src_lang`, the bridge runs a lightweight
heuristic (common Spanish function words) to detect ES vs EN.  This covers
the dominant Puente use-case without pulling in a full langdetect library.

Usage
-----
    bridge = PuenteBridge()
    bridge.on_card(lambda card: ble_send(card))

    # Called by Puente transcript handler:
    bridge.on_caption(
        text="No te preocupes, yo me encargo",
        confidence=0.94,
        speaker="Jordan",
    )
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from ..hud import cards as C

# ---------------------------------------------------------------------------
# Language heuristics
# ---------------------------------------------------------------------------
_ES_MARKERS = frozenset([
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "es", "son", "está", "están", "ser", "estar",
    "que", "en", "de", "del", "al", "con", "por", "para",
    "yo", "tú", "él", "ella", "nosotros", "vosotros", "ellos",
    "me", "te", "se", "nos", "le", "les",
    "no", "si", "sí", "pero", "porque", "cuando", "como",
    "muy", "más", "también", "ya", "aquí", "ahí",
])
_EN_MARKERS = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "i", "you", "he", "she", "we", "they",
    "and", "or", "but", "not", "if", "in", "on", "at", "to", "of",
    "this", "that", "it", "its", "my", "your", "his", "her",
    "have", "has", "do", "does", "will", "would", "can", "could",
])
_WORD_RE = re.compile(r"[\w']+")


def _detect_language(text: str) -> str:
    """Return 'es' or 'en' based on token overlap with marker sets."""
    tokens = {t.lower() for t in _WORD_RE.findall(text)}
    es_score = len(tokens & _ES_MARKERS)
    en_score = len(tokens & _EN_MARKERS)
    return "es" if es_score >= en_score else "en"


# ---------------------------------------------------------------------------
# PuenteBridge
# ---------------------------------------------------------------------------
class PuenteBridge:
    """Converts Puente caption events into LiveCaptionCard payloads."""

    def __init__(self, default_src: str = "es", default_dst: str = "en",
                 privacy=None) -> None:
        self._default_src = default_src
        self._default_dst = default_dst
        self._last_card: Optional[dict] = None
        self._card_callbacks: list[Callable[[dict], None]] = []
        # optional capture veil: a Puente caption is captured foreign speech, so
        # under the veil (pause OR incognito) the card must not carry it. Passed
        # through to live_caption_card, which blanks the content when blocked.
        # Defaults permissive (unwired seam); the orchestrator injects the real
        # gate when it wires Puente (refute-remediation 2026-07, defense-in-depth).
        self._privacy = privacy

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_card(self, cb: Callable[[dict], None]) -> None:
        """Register a callback invoked whenever a new LiveCaptionCard is ready."""
        self._card_callbacks.append(cb)

    # ------------------------------------------------------------------
    # Caption ingestion
    # ------------------------------------------------------------------

    def on_caption(
        self,
        text: str,
        confidence: float = 1.0,
        speaker: Optional[str] = None,
        src_lang: Optional[str] = None,
        translation: Optional[str] = None,
    ) -> dict:
        """Process a single Puente caption event.

        Parameters
        ----------
        text:        Raw transcript text from Puente (in src_lang).
        confidence:  ASR/MT confidence from Puente (0.0–1.0).
        speaker:     Optional speaker label (first name shown in eyebrow).
        src_lang:    ISO-639-1 source language; auto-detected if None.
        translation: Pre-translated text; if None, the card shows original
                     only (translation arrives in a follow-up event).

        Returns the LiveCaptionCard dict.
        """
        if not text:
            return {}

        # Language resolution
        detected = src_lang or _detect_language(text)
        dst = "en" if detected == "es" else "es"

        card = C.live_caption_card(
            original=text,
            translation=translation or "",
            src_lang=detected,
            dst_lang=dst,
            confidence=confidence,
            speaker=speaker,
            privacy=self._privacy,      # veil blanks the captured speech
        )
        self._last_card = card

        for cb in self._card_callbacks:
            try:
                cb(card)
            except Exception:
                pass

        return card

    def on_translation(
        self,
        original: str,
        translation: str,
        confidence: float = 1.0,
        speaker: Optional[str] = None,
        src_lang: Optional[str] = None,
    ) -> dict:
        """Update with final translation text (two-phase Puente flow).

        Puente sometimes fires the original caption first, then the
        translated text once the MT model has processed it.  This method
        handles the second event and re-emits the card with translation.
        """
        return self.on_caption(
            text=original,
            confidence=confidence,
            speaker=speaker,
            src_lang=src_lang,
            translation=translation,
        )

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def last_card(self) -> Optional[dict]:
        """Return the most recently produced card, or None."""
        return self._last_card

    def set_default_languages(self, src: str, dst: str) -> None:
        """Override default language pair (e.g. swap to EN→ES mode)."""
        self._default_src = src
        self._default_dst = dst
