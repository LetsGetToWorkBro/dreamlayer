"""v2/recipes.py — worked example figments for two Category-4 lenses that are
*content*, not new engine code (INNOVATION_SESSION 4.2, 4.3). Each is a pure
builder returning a budget-verified Figment authored in the same grammar a
rehearsed behavior uses — so they double as reference material and as the
`examples/figments/` the store can ship.

  Sous (4.2)  — a searing-station timer: hands-free, pulse the switch, flip.
  Kiln (4.3)  — a darkroom process ritual: chained timed stages that work with
                the Brain OFF; DOUBLE_NOD advances early, a low battery jumps to
                an explicit warning so the process never dies silently.
"""
from __future__ import annotations

from .figment import (
    END, CounterDecl, CounterOp, Figment, PulseSpec, Scene, TextLine, Transition,
)

_STOP = "long"           # a hold clears a running behavior
_ADV = "imu:double_nod"  # a deliberate double-nod advances the stage early
_BATT = "battery_low"


def _pulse(dur: float) -> PulseSpec:
    return PulseSpec(window_sec=min(5.0, max(0.5, dur)), color="accent_attention",
                     rate_hz=2.0)


def sous_sear_figment(sear_sec: float = 240.0, rest_sec: float = 30.0) -> Figment:
    """A searing station: SEAR counts down and pulses its final seconds;
    DOUBLE_NOD (or the timeout) flips to a short REST, then done."""
    fig = Figment(name="Sear", initial="sear")
    fig.add_scene(Scene(
        id="sear", duration_sec=float(sear_sec), tick="countdown",
        lines=[TextLine("SEAR", row=0, size="sm", color="accent_attention"),
               TextLine("{remaining}", row=1, size="lg")],
        pulse=_pulse(sear_sec),
        on_timeout=[Transition(target="rest")],
        on={_ADV: Transition(target="rest"), _STOP: Transition(target=END)}))
    fig.add_scene(Scene(
        id="rest", duration_sec=float(rest_sec), tick="countdown",
        lines=[TextLine("FLIP · REST", row=0, size="sm", color="accent_memory"),
               TextLine("{remaining}", row=1, size="lg")],
        pulse=_pulse(rest_sec),
        on_timeout=[Transition(target=END)],
        on={_STOP: Transition(target=END)}))
    return fig


def kiln_figment() -> Figment:
    """A darkroom print process: STOP-BATH -> FIX -> WASH, each timed and
    advanceable early with a double-nod, a print counter, and a low-battery
    escape. Fully on-glass — the radios can be dead."""
    fig = Figment(name="Darkroom", initial="stop")
    fig.battery_below = 15
    fig.add_counter(CounterDecl(name="print", start=1, lo=1, hi=9999))

    def stage(sid: str, label: str, dur: float, nxt: str, ops=None) -> Scene:
        return Scene(
            id=sid, duration_sec=float(dur), tick="countdown",
            lines=[TextLine(label, row=0, size="sm", color="accent_attention"),
                   TextLine("{remaining}", row=1, size="lg"),
                   TextLine("#{count:print}", row=3, size="sm", color="text_secondary")],
            on_timeout=[Transition(target=nxt, counter_ops=ops or [])],
            on={_ADV: Transition(target=nxt, counter_ops=ops or []),
                _STOP: Transition(target=END),
                _BATT: Transition(target="low")})

    fig.add_scene(stage("stop", "STOP-BATH", 30.0, "fix"))
    fig.add_scene(stage("fix", "FIX", 300.0, "wash"))
    fig.add_scene(stage("wash", "WASH", 600.0, END,
                        ops=[CounterOp("print", "inc", 1)]))
    fig.add_scene(Scene(
        id="low",
        lines=[TextLine("LOW BATTERY", row=0, size="sm", color="accent_attention"),
               TextLine("plug in", row=1, size="md")],
        duration_sec=5.0, on_timeout=[Transition(target=END)]))
    return fig


RECIPES = {"sous-sear": sous_sear_figment, "kiln-darkroom": kiln_figment}
