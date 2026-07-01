"""v2/teach.py — failures shown as beats, not reported as errors.

Every rejection becomes a TeachCard: which beat, what the compiler
understood, which physical limit it hit, and what to re-perform — in the
rehearsal vocabulary ("beat 3", "pulse", "fold"), never compiler
vocabulary. The card renders on the HUD (max 5 short lines) and in the
phone's Score view.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .budgets import BudgetReport, Violation
from .figment import MAX_PULSE_HZ, EMIT_REFILL_PER_S, MIN_SCENE_SEC
from .rehearsal import Beat


@dataclass
class TeachCard:
    title: str                       # eyebrow, e.g. "CAN'T DO THAT"
    lines: list[str]                 # <= 4 short lines for the HUD
    beat: Optional[int] = None       # which beat to re-perform
    suggestion: str = ""             # one action, in rehearsal words

    def hud_lines(self) -> list[str]:
        out = [self.title] + self.lines[:3]
        if self.suggestion:
            out.append(self.suggestion)
        return out[:5]

    def __str__(self) -> str:
        where = f" (beat {self.beat + 1})" if self.beat is not None else ""
        return f"{self.title}{where}: " + " ".join(self.lines) + \
               (f" → {self.suggestion}" if self.suggestion else "")


def _beat_phrase(beat: Optional[int]) -> str:
    return f"your beat {beat + 1}" if beat is not None else "your rehearsal"


def teach_violations(report: BudgetReport, beats: list[Beat]) -> TeachCard:
    """Translate the first (most important) violation into a card."""
    v: Violation = report.violations[0]

    if v.code == "pulse_rate":
        return TeachCard(
            title="CAN'T DO THAT",
            lines=[f"{_beat_phrase(v.beat)} asks the",
                   "screen to change faster",
                   f"than {MAX_PULSE_HZ:g}×/sec — Halo breathes,",
                   "it doesn't strobe"],
            beat=v.beat,
            suggestion='try "pulse" instead',
        )

    if v.code == "ble_flood":
        return TeachCard(
            title="CAN'T DO THAT",
            lines=[f"{_beat_phrase(v.beat)} would message",
                   "your phone more than",
                   f"{EMIT_REFILL_PER_S:g}×/sec — the radio",
                   "budget protects battery"],
            beat=v.beat,
            suggestion='say "send" once per round',
        )

    if v.code == "duration":
        return TeachCard(
            title="TOO QUICK",
            lines=[f"{_beat_phrase(v.beat)} is shorter",
                   f"than one breath ({MIN_SCENE_SEC:g}s)"],
            beat=v.beat,
            suggestion="speak a longer stretch",
        )

    if v.code in ("scene_count", "counter_count", "lines", "text_len"):
        return TeachCard(
            title="TOO MUCH AT ONCE",
            lines=["that's more than the",
                   "glass can hold in one",
                   "behavior"],
            beat=v.beat,
            suggestion="split it into two rehearsals",
        )

    if v.code == "livelock":
        return TeachCard(
            title="THAT NEVER RESTS",
            lines=["the loop you performed",
                   "has no moment of time",
                   "in it — it would spin"],
            beat=v.beat,
            suggestion="give the loop a duration",
        )

    return TeachCard(
        title="CAN'T STAGE THAT",
        lines=[f"{_beat_phrase(v.beat)} doesn't fit",
               "what Halo can safely run"],
        beat=v.beat,
        suggestion="re-perform that beat",
    )


def teach_inference(exc) -> TeachCard:
    """Translate an InferenceError (choreographer) into a card."""
    code = getattr(exc, "code", "unknown")
    beat = getattr(exc, "beat", None)

    if code == "empty":
        return TeachCard(
            title="EMPTY STAGE",
            lines=["I didn't catch any beats —",
                   "tap where the trigger goes,",
                   "speak the stretches of time"],
            suggestion='e.g. "rolling - three minutes"',
        )

    if code == "pulse_without_time":
        return TeachCard(
            title="PULSE NEEDS TIME",
            lines=[f"{_beat_phrase(beat)} marks a pulse",
                   "but nothing is counting",
                   "down yet"],
            beat=beat,
            suggestion="speak a duration first",
        )

    if code == "too_short":
        return TeachCard(
            title="TOO QUICK",
            lines=[f"{_beat_phrase(beat)} is shorter",
                   "than one breath"],
            beat=beat,
            suggestion="speak a longer stretch",
        )

    return TeachCard(
        title="LOST THE THREAD",
        lines=[f"I couldn't follow {_beat_phrase(beat)}"],
        beat=beat,
        suggestion="re-perform it",
    )
