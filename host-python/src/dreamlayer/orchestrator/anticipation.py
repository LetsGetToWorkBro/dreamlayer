"""orchestrator/anticipation.py — the right card at the right moment, unasked.

This is the engine that makes DreamLayer feel like it *anticipates* you. It
doesn't read your mind — it reads your context (where you are, the time, who's
in front of you, what you're tracking) and ties the existing signals together:

  • an event about to start                                   → "leave in 8 min"
  • a person you were introduced to, now in view              → their name + what
                                                                you owe each other
  • a place you're arriving at that holds something you left  → surface it

Each rule yields a Cue (a HUD card + a dedup key). The engine suppresses a cue
it recently showed (a cooldown), so nothing nags. The orchestrator gates the
whole thing behind the Privacy Veil. Pure and synthetic-testable: feed it a
Context, get back the cues it would flash.

(Distinct from memory/proactive.py, which fires place-signature triggers from
stored anchors; this ties *multiple* live signals into one ranked moment.)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..hud import cards


@dataclass
class Anchor:
    subject: str            # "bike", "car keys"
    place: str              # "4th & Alder north rack", "home"


@dataclass
class Event:
    title: str
    ts: float               # epoch seconds it starts
    place: str = ""


@dataclass
class Commitment:
    person: str
    task: str
    due_ts: float = 0.0


@dataclass
class Context:
    now: float
    place: str = ""                              # where you are, if known
    person: str = ""                             # a known person in view
    events: list = field(default_factory=list)   # Event
    anchors: list = field(default_factory=list)  # Anchor (things you left)
    commitments: list = field(default_factory=list)  # Commitment
    lead_minutes: float = 15.0                   # how early an event cues


@dataclass
class Cue:
    key: str                # dedup key
    kind: str               # "event" | "person" | "place"
    card: dict
    priority: int


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum() or ch == " ").strip()


def _match_place(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    return bool(na) and bool(nb) and (na in nb or nb in na)


class AnticipationEngine:
    """Turns context into a small, ranked, de-duplicated set of cues."""

    KINDS = ("event", "person", "place")

    def __init__(self, cooldown_s: float = 300.0):
        self.cooldown_s = cooldown_s
        self._shown: dict[str, float] = {}
        # which cue kinds are allowed — the app's proactive-cue picker toggles
        # these (event = "leave now", person = who's in front of you, place =
        # what you left here). All on by default.
        self.enabled_kinds: set[str] = set(self.KINDS)

    def set_kind(self, kind: str, on: bool = True) -> None:
        if kind not in self.KINDS:
            return
        if on:
            self.enabled_kinds.add(kind)
        else:
            self.enabled_kinds.discard(kind)

    def tick(self, ctx: Context) -> list[Cue]:
        cues: list[Cue] = []

        # 1) an event about to start — the most time-sensitive, highest priority
        for e in ctx.events:
            mins = (e.ts - ctx.now) / 60.0
            if 0 <= mins <= ctx.lead_minutes:
                cues.append(Cue(
                    key=f"event:{_norm(e.title)}:{int(e.ts)}", kind="event",
                    card=cards.upcoming_event(e.title, int(round(mins)), e.place),
                    priority=3))

        # 2) a person you were introduced to, now in front of you
        if ctx.person:
            owed = [c for c in ctx.commitments if _norm(c.person) == _norm(ctx.person)]
            detail = owed[0].task if owed else ""
            cues.append(Cue(
                key=f"person:{_norm(ctx.person)}", kind="person",
                card=cards.person_context(ctx.person, "you were introduced", detail),
                priority=2))

        # 3) arriving somewhere that holds something you left
        if ctx.place:
            for a in ctx.anchors:
                if _match_place(a.place, ctx.place):
                    cues.append(Cue(
                        key=f"place:{_norm(a.subject)}:{_norm(a.place)}", kind="place",
                        card=cards.here_reminder(a.subject, a.place), priority=1))

        # rank, drop disabled cue kinds, then drop anything shown within cooldown
        out: list[Cue] = []
        for c in sorted(cues, key=lambda c: -c.priority):
            if c.kind not in self.enabled_kinds:
                continue
            if ctx.now - self._shown.get(c.key, -1e9) >= self.cooldown_s:
                self._shown[c.key] = ctx.now
                out.append(c)
        return out
