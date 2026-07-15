"""v2/skill.py — Wayfinding: a procedure you step through hands-free.

Display name: **Wayfinding** — the linear-procedure authoring mode of the
Reality Compiler, alongside Rehearsal (reactive behaviors). Symbols stay
compile_skill / parse_skill / Step.

Cooking, a repair, a BJJ sequence — a curated list of steps that plays on
the HUD and advances at your pace: a tap moves to the next step, a timed
step (\"simmer 3 min\") also advances itself on the clock, and a long-press
bails out. This is not a new engine. It compiles straight to a **Figment**
(reality_compiler/v2), the same total, budget-verified scene machine the
device already runs — so a skill is as safe and as bounded as any rehearsed
behavior: no loops, every timed exit consumes real time, cost is provable
before it is signed.

    steps = parse_skill(\"\"\"
      1. Salt the water
      2. Boil for 8 minutes
      3. Drain and plate
    \"\"\")
    fig, report = compile_skill("Pasta", steps)   # report.ok is provable
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .figment import (
    Figment, Scene, TextLine, Transition, CounterDecl, CounterOp, PulseSpec,
    END, MAX_SCENES, MAX_LINES, MAX_TEXT_LEN, MIN_SCENE_SEC,
)
from .budgets import verify, BudgetReport

# content rows reserve the last line for the "n/N" step counter
_CONTENT_ROWS = MAX_LINES - 1

_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b",
                  re.IGNORECASE)
_UNIT_SEC = {"h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "hrs": 3600,
             "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
             "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}


@dataclass
class Step:
    """One instruction. hold_sec auto-advances a timed step, hands-free."""
    text: str
    hold_sec: Optional[float] = None


def _hold_from_text(text: str) -> Optional[float]:
    """The first duration named in a step becomes its auto-advance timer."""
    m = _DUR.search(text)
    if not m:
        return None
    unit = m.group(2).lower().rstrip(".")
    sec = float(m.group(1)) * _UNIT_SEC.get(unit, _UNIT_SEC.get(unit[0], 1))
    return max(MIN_SCENE_SEC, sec)


def parse_skill(text: str) -> list[Step]:
    """Parse a numbered/bulleted/newline list into steps. A duration in a
    line ("boil for 8 minutes") becomes that step's hands-free timer."""
    steps: list[Step] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        line = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line).strip()
        if not line:
            continue
        steps.append(Step(text=line, hold_sec=_hold_from_text(line)))
    return steps


def _wrap(text: str, max_rows: int) -> list[str]:
    """Greedy word-wrap into at most `max_rows` lines of MAX_TEXT_LEN."""
    words, rows, cur = text.split(), [], ""
    for w in words:
        w = w[:MAX_TEXT_LEN]
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= MAX_TEXT_LEN:
            cur += " " + w
        else:
            rows.append(cur)
            cur = w
            if len(rows) == max_rows:
                break
    if cur and len(rows) < max_rows:
        rows.append(cur)
    if not rows:
        rows = [""]
    # a step that overflows keeps its tail visible with an ellipsis
    if len(rows) == max_rows and len(" ".join(words)) > sum(len(r) + 1 for r in rows):
        rows[-1] = rows[-1][:MAX_TEXT_LEN - 1] + "…"
    return rows


def compile_skill(name: str, steps: list[Step],
                  verify_budgets: bool = True) -> tuple[Figment, Optional[BudgetReport]]:
    """Compile a step list into a budget-verified Figment.

    Each step is a scene: tap ("single") advances, a timed step also exits
    on its own clock, long-press bails to the end. A saturating "step"
    counter drives the "n/N" readout. Returns (figment, report); report is
    None when verify_budgets is False.
    """
    if not steps:
        raise ValueError("a skill needs at least one step")
    if len(steps) > MAX_SCENES:
        raise ValueError(f"a skill may have at most {MAX_SCENES} steps")

    n = len(steps)
    fig = Figment(name=name[:40] or "Skill", initial="s0",
                  meta={"kind": "skill", "steps": n})
    fig.add_counter(CounterDecl(name="step", start=1, lo=1, hi=n))

    for i, step in enumerate(steps):
        last = (i == n - 1)
        nxt = END if last else f"s{i + 1}"
        timed = step.hold_sec is not None

        # a timed step reserves an extra bottom row for its countdown, so
        # its instruction wraps into one fewer content line
        rows = _wrap(step.text, _CONTENT_ROWS - (1 if timed else 0))
        lines = [TextLine(content=r, row=r_i, size="md", color="text_primary")
                 for r_i, r in enumerate(rows)]
        row = len(rows)
        if timed:
            lines.append(TextLine(content="{remaining_s}s", row=row, size="sm",
                                  color="accent_attention"))
            row += 1
        lines.append(TextLine(content="{count:step}/%d" % n, row=row,
                              size="sm", color="text_secondary"))

        # advancing bumps the step counter (except off the last step)
        adv_ops = [] if last else [CounterOp(counter="step", op="inc", amount=1)]
        scene = Scene(id=f"s{i}", lines=lines)
        # tap always advances; long-press always bails to the end
        scene.on["single"] = Transition(target=nxt, counter_ops=list(adv_ops))
        scene.on["long"] = Transition(target=END)

        if timed:
            # a timed step advances itself, hands-free; the tap still skips
            assert step.hold_sec is not None   # `timed` is exactly this check
            scene.duration_sec = step.hold_sec
            scene.tick = "countdown"
            scene.on_timeout = [Transition(target=nxt, counter_ops=list(adv_ops))]
            scene.pulse = PulseSpec(window_sec=min(3.0, step.hold_sec),
                                    color="accent_attention", rate_hz=2.0)

        fig.add_scene(scene)

    report = verify(fig) if verify_budgets else None
    return fig, report
