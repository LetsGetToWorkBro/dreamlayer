"""v2/native.py — built-in behaviors Juno compiles for you.

The Reality Compiler is the engine; you don't have to *author* the everyday
things. Ask Juno — "set a timer for five minutes", "interval timer, thirty
seconds on, fifteen off, eight rounds", "show a clock" — and these builders
turn that into a budget-verified Figment that runs on the exact same on-glass
stage a rehearsed behavior runs on. No rehearsal, no keeping: they deploy
immediately and clear themselves.

Everything here is a *pure* builder returning a Figment that passes
budgets.verify() — the timer you get from a sentence is as bounded and safe as
one you performed by hand.
"""
from __future__ import annotations

from typing import Optional

from .figment import (
    END, SELF, Figment, Scene, TextLine, PulseSpec, Transition, GlyphSpec,
    CounterDecl, CounterOp, Guard, MIN_SCENE_SEC,
)
from .capabilities import require

# a calm end-of-phase pulse: the last few seconds breathe, never strobe
_PULSE_WINDOW = 5.0
_PULSE_HZ = 2.0
_STOP = "long"                       # a hold clears a running native behavior


def spoken_duration(secs: float) -> str:
    """'5 minutes', '1 minute 30 seconds' — how Juno says a length back."""
    secs = int(round(secs))
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    if s:
        parts.append(f"{s} second" + ("s" if s != 1 else ""))
    return " ".join(parts) or "0 seconds"


def _clamp(secs: float) -> float:
    return max(MIN_SCENE_SEC, round(float(secs), 3))


def _pulse(dur: float) -> PulseSpec:
    return PulseSpec(window_sec=min(_PULSE_WINDOW, dur),
                     color="accent_attention", rate_hz=_PULSE_HZ)


def timer_figment(seconds: float, label: str = "Timer") -> Figment:
    """A single countdown: label + m:ss ticking down, a pulse in the final
    seconds, then a brief DONE. A hold clears it early."""
    dur = _clamp(seconds)
    fig = Figment(name=label[:24] or "Timer", initial="run")
    fig.add_scene(Scene(
        id="run", duration_sec=dur, tick="countdown",
        lines=[
            TextLine(label.upper()[:24], row=0, size="sm", color="text_secondary"),
            TextLine("{remaining}", row=1, size="lg"),
        ],
        pulse=_pulse(dur),
        on_timeout=[Transition(target="done")],
        on={_STOP: Transition(target=END)},
    ))
    fig.add_scene(Scene(
        id="done", duration_sec=3.0,
        lines=[
            TextLine(label.upper()[:24], row=0, size="sm", color="text_secondary"),
            TextLine("DONE", row=1, size="lg", color="accent_success"),
        ],
        on_timeout=[Transition(target=END)],
    ))
    return fig


def interval_figment(work_sec: float, rest_sec: float,
                     rounds: Optional[int] = None,
                     label: str = "Intervals") -> Figment:
    """Work/rest intervals: a WORK countdown, a REST countdown, looping. With
    `rounds` it counts them and ends; without, it runs until you hold to stop.
    Each phase pulses in its final seconds so you feel the switch."""
    work = _clamp(work_sec)
    rest = _clamp(rest_sec)
    fig = Figment(name=label[:24] or "Intervals", initial="work")

    work_lines = [
        TextLine("WORK", row=0, size="sm", color="accent_attention"),
        TextLine("{remaining}", row=1, size="lg"),
    ]
    if rounds:
        fig.add_counter(CounterDecl(name="round", start=1, lo=0,
                                    hi=max(int(rounds), 1)))
        work_lines.append(TextLine("{count:round}/%d" % int(rounds), row=3,
                                   size="sm", color="text_secondary"))

    fig.add_scene(Scene(
        id="work", duration_sec=work, tick="countdown", lines=work_lines,
        pulse=_pulse(work),
        on_timeout=[Transition(target="rest")],
        on={_STOP: Transition(target=END)},
    ))

    if rounds:
        # after resting: end once we've done `rounds`, else next round
        rest_exit = [
            Transition(target=END, when=Guard("round", "ge", int(rounds))),
            Transition(target="work", counter_ops=[CounterOp("round", "inc", 1)]),
        ]
    else:
        rest_exit = [Transition(target="work")]

    fig.add_scene(Scene(
        id="rest", duration_sec=rest, tick="countdown",
        lines=[
            TextLine("REST", row=0, size="sm", color="accent_memory"),
            TextLine("{remaining}", row=1, size="lg"),
        ],
        pulse=_pulse(rest),
        on_timeout=rest_exit,
        on={_STOP: Transition(target=END)},
    ))
    return fig


def rosetta_figment(label: str = "Rosetta") -> Figment:
    """Rosetta Live, as a figment (the migration pilot — see docs/rc_v2/
    figment_migration.md). What someone is *saying*, in your language: the host
    detects the source language and translates each utterance, then streams
    three named slots onto the glass —

        {slot:langs}        the language pair, e.g. "ES → EN"
        {slot:translation}  the line in your language (primary)
        {slot:original}     what they actually said (secondary)

    It declares the ``translate`` capability: the figment shows the result, the
    Brain does the work (capabilities.py). A hold dismisses it. Unlike the
    SpokenCaptionCard it replaces on this path, the figment owns the screen and
    needs no per-card renderer twin — the whitelisted stage draws it, pinned by
    the same parity tests every figment gets."""
    fig = Figment(name=label[:24] or "Rosetta", initial="listen")
    fig.add_scene(Scene(
        id="listen",
        lines=[
            TextLine("{slot:langs}", row=0, size="sm", color="accent_memory"),
            TextLine("{slot:translation}", row=1, size="md"),
            TextLine("{slot:original}", row=3, size="sm", color="text_secondary"),
        ],
        on={
            "text": Transition(target=SELF),   # each utterance refreshes the slots
            _STOP: Transition(target=END),
        },
    ))
    return require(fig, "translate")


def morning_brief_figment(label: str = "Morning brief") -> Figment:
    """The day's brief as a figment (figment-migration, second card off the card
    path — see docs/rc_v2/figment_migration.md). On wake the host streams the
    Brain's synthesis + the first couple of points into named slots:

        YOUR DAY            (a fixed eyebrow, with a separator rule beneath it)
        {slot:synthesis}    the one-line read of the day (primary)
        {slot:point1/2}     the first two points (secondary)

    It owns the stage for ``dismiss`` seconds then clears itself, exactly like
    the SpokenCaptionCard→figment pilot; a hold dismisses it early. It needs no
    capability — the content is your own day, synthesized locally, not an
    external power. Drawn by the whitelisted stage, so no per-card renderer twin."""
    fig = Figment(name=label[:24] or "Morning brief", initial="brief")
    fig.add_scene(Scene(
        id="brief", duration_sec=8.0,
        lines=[
            TextLine("YOUR DAY", row=0, size="sm", color="accent_memory"),
            TextLine("{slot:synthesis}", row=1, size="md"),
            TextLine("{slot:point1}", row=3, size="sm", color="text_secondary"),
            TextLine("{slot:point2}", row=4, size="sm", color="text_secondary"),
        ],
        # a thin separator rule under the eyebrow (the paint layer — pure
        # decoration, drawn beneath the text), matching the card's separator
        glyphs=[GlyphSpec(points=[(0.19, 0.30), (0.81, 0.30)],
                          color="border_subtle", width="sm")],
        on_timeout=[Transition(target=END)],   # auto-clears after its window
        on={"long": Transition(target=END)},   # a hold dismisses it early
    ))
    return fig


def clock_figment(label: str = "Clock") -> Figment:
    """A persistent clock. The Figment shows {slot}; the host pushes the current
    time into the slot each minute (transport.text). A hold dismisses it."""
    fig = Figment(name=label[:24] or "Clock", initial="clock")
    fig.add_scene(Scene(
        id="clock",
        lines=[
            TextLine("{slot}", row=1, size="lg"),
        ],
        on={_STOP: Transition(target=END)},
    ))
    return fig
