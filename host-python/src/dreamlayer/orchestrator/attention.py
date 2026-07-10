"""orchestrator/attention.py — when Juno should say "Listen!"

The anticipation engine decides *what card* to show; this decides *when it's
worth interrupting you out loud*. It reads the same live Context (where you are,
who's in front of you, what's on the calendar, what you left behind, what you
owe) and emits Alerts at two levels:

  • listen   — worth a glance: a commitment about to slip, someone you owe now
               in front of you, something you're walking away from.
  • watchout — genuinely time-critical: you need to leave *now*.

Pure and deterministic like the anticipation engine — feed it a Context, get
the alerts back. The orchestrator turns the top fresh one into a hark (Juno's
"Listen!"/"Watch out!"), which carries its own Veil/Focus gating and pacing. A
per-key cooldown here means the *same* alert never nags, even as the moment
lingers.
"""
from __future__ import annotations

from dataclasses import dataclass

from .anticipation import Context, Event, Anchor, Commitment, _norm, _match_place


@dataclass
class Alert:
    level: str      # "listen" | "watchout"
    clue: str       # the line Juno speaks
    detail: str     # a short second line
    key: str        # dedup key — one alert per real thing


class AttentionPolicy:
    """Turns context into a small, ranked, de-duplicated set of interruptions."""

    def __init__(self, leave_now_s: float = 360.0, slip_window_s: float = 2 * 86400.0,
                 per_key_cooldown_s: float = 1800.0):
        self.leave_now_s = leave_now_s          # ≤ this to an event → "leave now"
        self.slip_window_s = slip_window_s      # a due commitment within this → nudge
        self.per_key_cooldown_s = per_key_cooldown_s
        self._alerted: dict[str, float] = {}    # key → last time we raised it
        self._last_place = ""                   # to notice you *leaving* somewhere

    def evaluate(self, ctx: Context, commitments=None) -> list[Alert]:
        commitments = commitments if commitments is not None else ctx.commitments
        out: list[Alert] = []

        # 1) an event you must leave for right now → WATCH OUT (time-critical)
        for e in ctx.events:
            secs = e.ts - ctx.now
            if 0 <= secs <= self.leave_now_s:
                mins = max(0, int(round(secs / 60)))
                when = "now" if mins == 0 else f"{mins} min"
                out.append(Alert("watchout", f"{when} to {e.title}",
                                 (f"leave for {e.place}" if e.place else ""),
                                 f"event:{_norm(e.title)}:{int(e.ts)}"))

        # 2) someone you owe, now in front of you → LISTEN
        if ctx.person:
            for c in commitments:
                if _norm(c.person) == _norm(ctx.person):
                    out.append(Alert("listen", f"You owe {ctx.person} — {c.task}",
                                     "from your commitments",
                                     f"owe:{_norm(c.person)}:{_norm(c.task)}"))

        # 3) you're walking away from a place where you left something → LISTEN
        if self._last_place and not _match_place(self._last_place, ctx.place):
            for a in ctx.anchors:
                if _match_place(a.place, self._last_place):
                    out.append(Alert("listen", f"You're leaving your {a.subject}",
                                     a.place, f"left:{_norm(a.subject)}:{_norm(a.place)}"))
        self._last_place = ctx.place

        # 4) a commitment about to slip (a real due time approaching) → LISTEN
        for c in commitments:
            due = getattr(c, "due_ts", 0.0)
            if due and 0 < due - ctx.now <= self.slip_window_s:
                out.append(Alert("listen", c.task, f"you owe {c.person}",
                                 f"slip:{_norm(c.person)}:{_norm(c.task)}"))

        # drop anything still on its per-key cooldown; watch-outs rank first
        fresh = [a for a in out
                 if ctx.now - self._alerted.get(a.key, -1e18) >= self.per_key_cooldown_s]
        fresh.sort(key=lambda a: 0 if a.level == "watchout" else 1)
        return fresh

    def mark(self, key: str, now: float) -> None:
        """Remember we raised `key` so it won't nag until the cooldown passes."""
        self._alerted[key] = now
