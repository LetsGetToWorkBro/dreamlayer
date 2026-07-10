"""orchestrator/candor.py — Candor Mirror (INNOVATION_SESSION 2.7).

Your glasses coach *you* about *you*. One inward-aimed pipeline, two registers:

  • Live — a rolling 30s window of your own speech normalises to a single quiet
    pace arc on the ring (the Cinema `amp` message, {v: 0..99}); a `notice` when
    you sustain a rushed pace; the filler tally stays hidden until you peek.
  • Post-mortem — at the end of a conversation, a KeptCard: "162 wpm (↑), 9
    'um's, and you told the project story differently than Tuesday." Never live,
    always after.

A deception pipeline pointed at *others* is a scandal; pointed at *yourself*
it's a coach — and only an open codebase can prove which one it is. This one is
inward-only: it reads your words (fed from self-attributed captions), never
anyone else's, and the Privacy Veil silences it completely. It composes the
shipped `plugins/filler.py` counter and takes the narrative-drift line from
`consistency.py` (Candor) as an input — it never invents one.
"""
from __future__ import annotations

import re
import time
from collections import Counter, deque
from typing import Optional

from ..plugins.filler import FILLERS

# WPM → the arc's amplitude. Below LO reads as calm, above HI as maxed; the band
# in between is where a talk actually lives.
WPM_LO, WPM_HI = 90.0, 200.0
FAST_WPM = 165.0          # sustained above this earns a `notice` haptic
WINDOW_S = 30.0           # the rolling live window
_MIN_SPAN_S = 2.0         # don't extrapolate WPM from a sub-2s burst

_FILLER_SET = tuple(FILLERS)
# per-filler word-boundary matchers, so counts survive punctuation ("um, so")
_FILLER_RE = {f: re.compile(r"\b" + re.escape(f) + r"\b", re.I) for f in _FILLER_SET}


def _wordcount(text: str) -> int:
    return len([w for w in (text or "").split() if any(c.isalnum() for c in w)])


def _found_fillers(text: str) -> list[str]:
    out: list[str] = []
    for f, rx in _FILLER_RE.items():
        out.extend([f] * len(rx.findall(text or "")))
    return out


class CandorMirror:
    """The self-coach. Feed it your own transcribed lines with `observe`; read
    the live arc with `live_frame`, and the debrief with `post_mortem`."""

    def __init__(self, privacy=None, now_fn=None):
        self._privacy = privacy
        self._now = now_fn or time.time
        self._window: deque = deque()        # (ts, words) inside the live window
        self._fillers: Counter = Counter()
        self._total_words = 0
        self._first_ts: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._history: list[float] = []      # past sessions' wpm (for the trend)

    def _veiled(self) -> bool:
        return (self._privacy is not None
                and hasattr(self._privacy, "allow_capture")
                and not self._privacy.allow_capture())

    # -- intake --------------------------------------------------------------

    def observe(self, text: str, now: Optional[float] = None) -> None:
        """Fold one self-attributed line in. A no-op while veiled — the coach
        never learns from what you asked it not to see."""
        if self._veiled() or not text:
            return
        ts = self._now() if now is None else now
        words = _wordcount(text)
        if words == 0:
            return
        if self._first_ts is None:
            self._first_ts = ts
        self._last_ts = ts
        self._total_words += words
        self._window.append((ts, words))
        self._trim(ts)
        for f in _found_fillers(text):
            self._fillers[f] += 1

    def _trim(self, now: float) -> None:
        while self._window and now - self._window[0][0] > WINDOW_S:
            self._window.popleft()

    # -- the live register ---------------------------------------------------

    def live_wpm(self, now: Optional[float] = None) -> float:
        now = self._now() if now is None else now
        self._trim(now)
        if not self._window:
            return 0.0
        span = max(_MIN_SPAN_S, now - self._window[0][0])
        words = sum(w for _, w in self._window)
        return words / span * 60.0

    def amp(self, now: Optional[float] = None) -> int:
        """0..99 for the Cinema `amp` arc."""
        w = self.live_wpm(now)
        frac = (w - WPM_LO) / (WPM_HI - WPM_LO)
        return int(max(0, min(99, round(frac * 99))))

    def notice(self, now: Optional[float] = None) -> bool:
        return self.live_wpm(now) > FAST_WPM

    def live_frame(self, now: Optional[float] = None) -> Optional[dict]:
        """One BLE frame's worth of the live arc, or None while veiled. The
        filler total rides along for a GLANCE_PEEK reveal — never shown unasked."""
        if self._veiled():
            return None
        return {"amp": self.amp(now), "notice": self.notice(now),
                "fillers": self.filler_total()}

    def filler_total(self) -> int:
        return sum(self._fillers.values())

    # -- the post-mortem -----------------------------------------------------

    def session_wpm(self) -> float:
        if self._first_ts is None or self._last_ts is None:
            return 0.0
        span = max(_MIN_SPAN_S, self._last_ts - self._first_ts)
        return self._total_words / span * 60.0

    def _trend(self, wpm: float) -> str:
        if not self._history:
            return ""
        mean = sum(self._history) / len(self._history)
        if wpm > mean * 1.08:
            return "↑"
        if wpm < mean * 0.92:
            return "↓"
        return "→"

    def post_mortem(self, drift: Optional[str] = None) -> Optional[dict]:
        """A debrief KeptCard at the end of a conversation, or None while veiled
        (or with nothing heard). `drift` is the narrative-consistency line from
        Candor's consistency engine, folded in when present — never invented.
        Records this session's pace so the next debrief can show a trend."""
        if self._veiled() or self._first_ts is None:
            return None
        wpm = round(self.session_wpm())
        trend = self._trend(self.session_wpm())
        top = self._fillers.most_common(3)
        self._history.append(self.session_wpm())     # for next time's ↑/↓

        pace = f"{wpm} wpm{(' ' + trend) if trend else ''}"
        filler_line = ""
        if top:
            filler_line = ", ".join(f"{n} '{w}'" for w, n in top)
        lines = ["How you spoke", pace]
        if filler_line:
            lines.append(filler_line)
        if drift:
            lines.append(drift)
        return {
            "type": "CandorCard",
            "dismiss_ms": 8000,
            "eyebrow": "How you spoke",
            "primary": pace,
            "fillers": filler_line,
            "wpm": wpm,
            "trend": trend,
            "drift": drift or "",
            "color": "accent_memory",
            "lines": lines,
        }

    def reset(self) -> None:
        """Start a fresh conversation (keeps the cross-session pace history)."""
        self._window.clear()
        self._fillers.clear()
        self._total_words = 0
        self._first_ts = self._last_ts = None
