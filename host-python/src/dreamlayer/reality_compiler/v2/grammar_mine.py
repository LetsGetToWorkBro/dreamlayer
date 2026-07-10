"""v2/grammar_mine.py — grammar mining (INNOVATION_SESSION 5.3, last sub-part).

The rehearsal grammar is closed: a beat the parser doesn't recognise falls
through to *label text* (`parse_utterance -> ("label", ...)`). Most fall-throughs
are genuine labels ("rolling", "the sear") — diverse, one-off. But a *recurring*
word across many fall-throughs is a signal: people keep trying to say a thing the
grammar can't hear yet. "vibrate" showing up 40 times isn't 40 labels — it's a
feature request. Mining those near-misses turns the compiler's roadmap into a
measurement.

Local by design. This counts *tokens*, never stores whole sentences, and lives
in one file on your device. The community-aggregate side — opt-in, counts-only,
through the registry — is a separate step (OWNER); nothing here leaves the box.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# already in the grammar (see parse_utterance) or too generic to be a signal —
# a hit on one of these is not a missing feature.
_KNOWN = {
    "done", "finish", "pulse", "flash", "strobe", "blink", "warn", "count",
    "tally", "send", "tell", "log", "show", "again", "repeat", "repeats",
    "loop", "until", "tap", "hold", "press", "double", "single",
}
_STOP = {
    "a", "an", "the", "to", "and", "then", "at", "in", "on", "of", "for",
    "me", "my", "it", "this", "these", "them", "that", "s", "i", "m", "is",
    "with", "your", "you", "every", "second", "seconds", "minute", "minutes",
    "min", "mins", "sec", "secs", "phone", "please", "just", "some", "up",
}
_TOKEN = re.compile(r"[a-z]{3,}")     # words only; ≥3 letters; numbers dropped


class GrammarMiner:
    """Counts unrecognised command-candidate tokens from fall-through beats."""

    def __init__(self, path: Optional[Path | str] = None):
        self._path = Path(path) if path else None
        self._counts: dict[str, int] = {}
        self._hydrate()

    def observe(self, text: str, parsed: tuple) -> None:
        """Record one parsed beat. Only fall-throughs (`("label", …)`) are
        mined; a recognised command teaches nothing about a missing word."""
        if not parsed or parsed[0] != "label":
            return
        new = False
        for tok in self._tokens(text):
            self._counts[tok] = self._counts.get(tok, 0) + 1
            new = True
        if new:
            self._persist()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        out = []
        for tok in _TOKEN.findall((text or "").lower()):
            if tok in _KNOWN or tok in _STOP:
                continue
            out.append(tok)
        return out

    def candidates(self, top: int = 10, min_count: int = 2) -> list[dict]:
        """The most-requested words the grammar can't hear yet, commonest first.
        `min_count` filters out one-off labels — a real candidate recurs."""
        ranked = sorted(((w, c) for w, c in self._counts.items() if c >= min_count),
                        key=lambda wc: (-wc[1], wc[0]))
        return [{"word": w, "count": c} for w, c in ranked[:top]]

    # -- local persistence ---------------------------------------------------

    def _hydrate(self) -> None:
        if self._path and self._path.exists():
            try:
                self._counts = {str(k): int(v) for k, v in
                                json.loads(self._path.read_text()).items()}
            except (ValueError, OSError):
                self._counts = {}

    def _persist(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._counts, sort_keys=True))
        except OSError:
            pass
