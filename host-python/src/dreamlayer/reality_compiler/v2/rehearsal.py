"""v2/rehearsal.py — the stage where behaviors are performed, not described.

A RehearsalSession records *beats*:

  taps    — tap() / double_tap() / long_press(): where triggers live
  speech  — say("rolling - three minutes"): durations are spoken instead
            of lived (time-folding), marks name what matters ("pulse",
            "count this", "again", "until I double-tap", "done")
  dwell   — dwell(3): short real pauses kept as literal beats

Speech is parsed against a closed, offline grammar (parse_utterance).
Words outside the grammar become *label text* — there is no way to speak
your way into an unsafe machine, because the vocabulary has no unsafe
words.

finish() hands the beat trace to the choreographer, verifies budgets,
and returns a RehearsalResult carrying either a signed-ready Figment plus
its time-folded run-through, or a TeachCard explaining — in beats, not
compiler-speak — what could not be staged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Beats
# ---------------------------------------------------------------------------

@dataclass
class Beat:
    kind: str                   # tap | double_tap | long_press | say | dwell
    index: int
    text: Optional[str] = None          # raw utterance (say)
    seconds: Optional[float] = None     # dwell length
    parsed: Optional[tuple] = None      # grammar reading (say)

    def reading(self) -> str:
        """Plain-words reading shown on the stage as the beat lands."""
        if self.kind == "double_tap":
            return "strong beat (double-tap)"
        if self.kind == "tap":
            return "beat (tap)"
        if self.kind == "long_press":
            return "hold"
        if self.kind == "dwell":
            return f"{self.seconds:g}s pause"
        p = self.parsed or ("label", self.text)
        tag = p[0]
        if tag == "duration":
            label, secs = p[1], p[2]
            mins = f"{int(secs // 60)}:{int(secs % 60):02d}"
            return f"{label or 'stretch'} — {mins} folded"
        if tag == "pulse":
            return f"pulse mark (last {p[1]:g}s)"
        if tag == "warn":
            return f"warn mark (last {p[1]:g}s)"
        if tag == "count":
            return "count mark"
        if tag == "emit":
            return f"send mark ({p[1]})"
        if tag == "loop":
            return "repeat mark" + (f" ×{p[1]}" if p[1] else "")
        if tag == "until":
            return f"until {p[1]}"
        if tag == "show":
            return f"show {p[1]!r}"
        if tag == "done":
            return "done"
        return f"label {self.text!r}"


# ---------------------------------------------------------------------------
# The closed grammar
# ---------------------------------------------------------------------------

_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "ninety": 90, "a": 1, "an": 1,
}

_NUM = r"(\d+(?:\.\d+)?|" + "|".join(_WORD_NUM) + r")"


def _num(tok: str) -> float:
    return _WORD_NUM.get(tok, None) if tok in _WORD_NUM else float(tok)


def _find_duration(t: str) -> Optional[float]:
    m = re.search(_NUM + r"\s*(minutes?|mins?|min\b)", t)
    if m:
        return _num(m.group(1)) * 60
    m = re.search(_NUM + r"\s*(seconds?|secs?|sec\b)", t)
    if m:
        return _num(m.group(1))
    return None


def _find_rate(t: str) -> Optional[float]:
    m = re.search(_NUM + r"\s*times?\s*(?:a|per)\s*second", t)
    if m:
        return _num(m.group(1))
    if "every frame" in t:
        return 30.0
    return None


def parse_utterance(text: str) -> tuple:
    """Parse one spoken beat against the closed rehearsal grammar.

    Returns one of:
      ("done",)                      ("duration", label, seconds)
      ("pulse", window_s, rate_hz)   ("warn", window_s)
      ("count", label)               ("emit", tag, per_second)
      ("loop", times|None)           ("until", event)
      ("show", text)                 ("label", text)
    """
    raw = text.strip()
    t = re.sub(r"[—–]", "-", raw.lower())
    t = re.sub(r"[^\w\s:%.-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    if t in ("done", "i m done", "that s it", "finish"):
        return ("done",)

    m = re.search(r"until i (double.?tap|tap|hold|long.?press)", t)
    if m:
        g = m.group(1).replace("-", " ").replace("_", " ")
        event = {"double tap": "double", "doubletap": "double",
                 "tap": "single", "hold": "long", "long press": "long"}[g]
        return ("until", event)

    if re.search(r"\bagain\b|\brepeats?\b|keeps going|starts over", t):
        m = re.search(_NUM + r"\s*(times|rounds)", t)
        times = int(_num(m.group(1))) if m else None
        return ("loop", times)

    if re.search(r"\bpulse\b|\bflash\b|\bstrobe\b|\bblink\b", t):
        window = _find_duration(t) or 10.0
        rate = _find_rate(t)
        if rate is None:
            rate = 4.0 if re.search(r"\bstrobe\b|\bflash\b", t) else 2.0
        return ("pulse", window, rate)

    if "warn me" in t or t.startswith("warn"):
        window = _find_duration(t) or 10.0
        return ("warn", window)

    if re.search(r"\bcount\b|\btally\b", t):
        label = re.sub(r".*\b(count|tally)\b( this| these| them)?", "", t).strip()
        return ("count", label or "count")

    m = re.search(r"\b(send|tell my phone|log)\b\s*(?:a |an |the )?(\w+)?", t)
    if m and m.group(1):
        tag = (m.group(2) or "mark")[:16]
        per_second = _find_rate(t)
        if per_second is None and "every second" in t:
            per_second = 1.0
        return ("emit", tag, per_second)

    m = re.match(r"show\s+(.*)", t)
    if m:
        shown = raw[len(raw) - len(m.group(1)):].strip() or m.group(1)
        return ("show", shown[:24])

    secs = _find_duration(t)
    if secs is not None:
        # leading words before the number are the scene label
        m = re.search(_NUM, t)
        label = t[:m.start()].strip(" -,") if m else ""
        label = re.sub(r"\b(for|lasts?|pass(es)?|of)\b", "", label).strip(" -,")
        return ("duration", label, secs)

    return ("label", raw[:24])


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@dataclass
class RehearsalResult:
    ok: bool
    figment: Optional[object] = None          # Figment
    report: Optional[object] = None           # BudgetReport
    teach: Optional[object] = None            # TeachCard
    playback: list = field(default_factory=list)   # PlaybackFrames
    beats: list[Beat] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return (f"Kept-ready: {self.figment.name!r} "
                    f"({self.report.scene_count} scenes, "
                    f"display<={self.report.worst_display_hz:g}Hz, "
                    f"emit<={self.report.worst_emit_per_sec:g}/s)")
        return f"Can't stage that: {self.teach.title}"


class RehearsalSession:
    """One open stage. Feed beats, then finish()."""

    def __init__(self, name: str = "Rehearsed behavior",
                 fold_seed: int = 7) -> None:
        self.name = name
        self.fold_seed = fold_seed
        self.beats: list[Beat] = []
        self._done = False

    # -- beat inputs -----------------------------------------------------

    def tap(self) -> Beat:
        return self._add(Beat("tap", len(self.beats)))

    def double_tap(self) -> Beat:
        return self._add(Beat("double_tap", len(self.beats)))

    def long_press(self) -> Beat:
        return self._add(Beat("long_press", len(self.beats)))

    def dwell(self, seconds: float) -> Beat:
        return self._add(Beat("dwell", len(self.beats), seconds=seconds))

    def say(self, text: str) -> Beat:
        parsed = parse_utterance(text)
        beat = self._add(Beat("say", len(self.beats), text=text, parsed=parsed))
        if parsed[0] == "done":
            self._done = True
        return beat

    def _add(self, beat: Beat) -> Beat:
        if self._done:
            raise RuntimeError("rehearsal already finished — reopen the stage")
        self.beats.append(beat)
        return beat

    # -- correction: re-perform one beat ----------------------------------

    def redo(self, index: int, replacement: Beat | str) -> Beat:
        """Re-perform beat `index`. Strings are treated as new utterances."""
        if isinstance(replacement, str):
            replacement = Beat("say", index, text=replacement,
                               parsed=parse_utterance(replacement))
        replacement.index = index
        self.beats[index] = replacement
        return replacement

    # -- finish ------------------------------------------------------------

    def finish(self) -> RehearsalResult:
        from . import budgets
        from .choreographer import Choreographer, InferenceError
        from .playback import run_through
        from .teach import teach_inference, teach_violations

        beats = [b for b in self.beats
                 if not (b.parsed and b.parsed[0] == "done")]
        try:
            fig = Choreographer().infer(beats, name=self.name)
        except InferenceError as exc:
            return RehearsalResult(ok=False, teach=teach_inference(exc),
                                   beats=self.beats)
        report = budgets.verify(fig)
        if not report.ok:
            return RehearsalResult(ok=False, report=report,
                                   teach=teach_violations(report, self.beats),
                                   beats=self.beats)
        frames = run_through(fig, seed=self.fold_seed)
        return RehearsalResult(ok=True, figment=fig, report=report,
                               playback=frames, beats=self.beats)
