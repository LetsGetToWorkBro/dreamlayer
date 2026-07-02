"""confluence/duet.py — two performers, one figment.

A Duet Rehearsal is Rehearsal with the stage doubled: both bonded
wearers' beats land in one shared trace — the coach taps where the
trigger goes, the student speaks the durations, either can mark the
pulse — and the choreographer compiles one Figment both keep. Each
phone signs its own copy with its own session key (a duet shares a
behavior, never a key), so both Repertoires own it independently and
either side can revoke theirs without touching the other's.

Correction stays Rehearsal-shaped: either performer can re-perform any
beat, whoever originally performed it. The Score view shows whose beat
is whose; the compiled machine doesn't care.
"""
from __future__ import annotations

from typing import Optional

from ..reality_compiler.v2.rehearsal import (
    Beat, RehearsalSession, RehearsalResult, parse_utterance,
)


class DuetSession:
    """One shared beat trace, two performers."""

    def __init__(self, name: str = "Duet behavior",
                 performers: tuple[str, str] = ("a", "b")) -> None:
        self._session = RehearsalSession(name=name)
        self.performers = performers
        self.credits: list[str] = []          # who performed beat i

    # -- both sides perform into the same trace -----------------------------

    def _credit(self, who: str) -> None:
        if who not in self.performers:
            raise ValueError(f"unknown performer {who!r}")
        self.credits.append(who)

    def tap(self, who: str) -> Beat:
        self._credit(who)
        return self._session.tap()

    def double_tap(self, who: str) -> Beat:
        self._credit(who)
        return self._session.double_tap()

    def long_press(self, who: str) -> Beat:
        self._credit(who)
        return self._session.long_press()

    def say(self, who: str, text: str) -> Beat:
        self._credit(who)
        return self._session.say(text)

    def dwell(self, who: str, seconds: float) -> Beat:
        self._credit(who)
        return self._session.dwell(seconds)

    def redo(self, who: str, index: int, replacement: str) -> Beat:
        """Either performer corrects any beat — the fix takes the
        credit."""
        if who not in self.performers:
            raise ValueError(f"unknown performer {who!r}")
        beat = self._session.redo(index, replacement)
        if index < len(self.credits):
            self.credits[index] = who
        return beat

    # -- one machine, two owners -----------------------------------------------

    def finish(self) -> RehearsalResult:
        result = self._session.finish()
        if result.ok:
            result.figment.meta["duet"] = {
                "performers": list(self.performers),
                "credits": list(self.credits),
            }
        return result

    def score(self) -> list[tuple[str, str]]:
        """(performer, reading) per beat — the shared Score view."""
        return [(self.credits[i] if i < len(self.credits) else "?",
                 beat.reading())
                for i, beat in enumerate(self._session.beats)]


def keep_for_both(result: RehearsalResult, rc_a, rc_b):
    """Both compilers keep their own signed copy: shared behavior,
    separate keys, independent revocation."""
    if not result.ok:
        raise ValueError(f"duet did not compile: {result.teach}")
    return rc_a.keep(result.figment), rc_b.keep(result.figment)
