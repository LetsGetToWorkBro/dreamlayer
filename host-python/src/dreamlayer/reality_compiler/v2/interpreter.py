"""v2/interpreter.py — reference interpreter for Figment semantics.

The Python twin of halo-lua/app/figment_stage.lua. Both implement exactly
these semantics; the test suite pins them, and playback/preview and the
demo renderer run on this one.

Determinism: pass `rng` (e.g. random.Random(seed)) so random-duration
scenes (react timer) are reproducible in tests and previews.

Defense in depth: even though budgets.verify() proves the emit budget
statically, the interpreter enforces a runtime token bucket too (as the
Lua stage does), so a forged figment that skipped verification still
cannot flood BLE.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from . import contracts
from .figment import (
    Figment, Scene, Transition, GlyphSpec, SLOT_TOKEN_RE,
    END, SELF, EMIT_BURST, EMIT_REFILL_PER_S, MAX_TEXT_LEN, MAX_SLOTS,
)


@dataclass
class ResolvedLine:
    text: str
    row: int
    size: str
    color: str


@dataclass
class DisplayFrame:
    """What the stage would draw right now."""
    scene: str
    lines: list[ResolvedLine] = field(default_factory=list)
    glyphs: list[GlyphSpec] = field(default_factory=list)  # painted strokes
    pulse_on: bool = False
    pulse_color: Optional[str] = None
    cadence_phase: str = ""            # "in" | "hold" | "out" | "" (no cadence)
    cadence_level: float = 0.0         # breathing amplitude, 0..1
    ended: bool = False


def _fmt_clock(secs: float) -> str:
    secs = max(0, int(math.ceil(secs)))
    if secs >= 60:
        return f"{secs // 60}:{secs % 60:02d}"
    return str(secs)


class Stage:
    """Runs one Figment. step(dt) advances time; inject(event) delivers
    external events; frame() renders the current display state."""

    def __init__(self, fig: Figment, rng: Optional[random.Random] = None,
                 battery_level: int = 100) -> None:
        self.fig = fig
        self.rng = rng or random.Random()
        self.battery_level = battery_level
        self.counters: dict[str, int] = {
            n: c.start for n, c in fig.counters.items()}
        # Host-pushed text ("text" event). "" is the default {slot}; named
        # {slot:<name>} slots share the dict. Bounded to MAX_SLOTS named keys.
        self.slots: dict[str, str] = {"": ""}
        self.emits: list[tuple[float, str]] = []   # (t, tag) delivered
        self.recorded: list[tuple[float, str]] = []  # (t, tag) flagged record=True
        self.dropped_emits: int = 0      # clamped by token bucket
        self.ended = False
        self.clock = 0.0
        self._tokens = float(EMIT_BURST)
        self._last_elapsed = 0.0         # frozen {elapsed} after scene exit
        self._battery_cooldown = 0.0
        self._enter(fig.initial)

    # ------------------------------------------------------------------
    # Time and events
    # ------------------------------------------------------------------

    def step(self, dt: float = 1.0) -> None:
        """Advance dt seconds (may cross several scene timeouts)."""
        if self.ended:
            return
        remaining_dt = dt
        # bounded by construction: each timeout consumes >= MIN_SCENE_SEC
        while remaining_dt > 1e-9 and not self.ended:
            if self._duration is None:
                self._advance_clock(remaining_dt)
                break
            left = self._duration - self.scene_elapsed
            if remaining_dt < left - 1e-9:
                self._advance_clock(remaining_dt)
                break
            self._advance_clock(left)
            remaining_dt -= left
            self._timeout()

    def _advance_clock(self, dt: float) -> None:
        self.clock += dt
        self.scene_elapsed += dt
        self._tokens = contracts.refill_tokens(
            self._tokens, dt, EMIT_REFILL_PER_S, float(EMIT_BURST))
        if self._battery_cooldown > 0:
            self._battery_cooldown -= dt
        if (self.fig.battery_below is not None
                and self.battery_level < self.fig.battery_below
                and self._battery_cooldown <= 0):
            self._battery_cooldown = 60.0
            self._dispatch("battery_low")

    def inject(self, event: str, text: Optional[str] = None) -> bool:
        """Deliver an external event ("single", "double", "long", "imu_tap",
        "ble", "ble:<n>", "text", "text:<slot>"). A "text[:<slot>]" event feeds
        the (named) host slot and fires the base "text" trigger. Returns True if
        handled."""
        if self.ended:
            return False
        if event == "text" or event.startswith("text:"):
            name = event[5:] if event.startswith("text:") else ""
            if text is not None:
                # bound the dict: accept the default slot and known names always;
                # a new named slot only until MAX_SLOTS distinct named keys exist.
                named = [k for k in self.slots if k]
                if contracts.accept_slot(
                        name == "", name in self.slots, len(named), MAX_SLOTS):
                    self.slots[name] = contracts.clamp_text(text, MAX_TEXT_LEN)
            return self._dispatch("text")
        return self._dispatch(event)

    def _dispatch(self, event: str) -> bool:
        scene = self._scene()
        t = scene.on.get(event)
        if t is None and event.startswith("ble:"):
            t = scene.on.get("ble")
        if t is None:
            return False
        self._take(t)
        return True

    def _timeout(self) -> None:
        scene = self._scene()
        for t in scene.on_timeout:
            if t.when is None or self._guard(t):
                self._take(t)
                return
        self._end()

    def _guard(self, t: Transition) -> bool:
        g = t.when
        assert g is not None   # only called past the `t.when is None` short-circuit
        val = self.counters.get(g.counter, 0)
        if g.cmp == "ge":
            return val >= g.value
        if g.cmp == "le":
            return val <= g.value
        return val == g.value

    def _take(self, t: Transition) -> None:
        for op in t.counter_ops:
            decl = self.fig.counters[op.counter]
            self.counters[op.counter] = contracts.saturate(
                self.counters[op.counter], op.op, op.amount, decl.lo, decl.hi)
        if t.emit is not None:
            spent, self._tokens = contracts.spend_token(self._tokens)
            if spent:
                self.emits.append((self.clock, t.emit))
                # 5.1 #5 ledger emits: a recorded emit is data you keep — the
                # deployer drains `recorded` into the Vault performance log.
                if t.record:
                    self.recorded.append((self.clock, t.emit))
            else:
                self.dropped_emits += 1
        if t.target == END:
            self._end()
        elif t.target == SELF:
            self._enter(self.current)
        else:
            self._enter(t.target)

    def _enter(self, scene_id: str) -> None:
        self._last_elapsed = getattr(self, "scene_elapsed", 0.0)
        self.current = scene_id
        self.scene_elapsed = 0.0
        s = self._scene()
        if s.duration_range is not None:
            lo, hi = s.duration_range
            self._duration: Optional[float] = self.rng.uniform(lo, hi)
        else:
            self._duration = s.duration_sec

    def _end(self) -> None:
        self._last_elapsed = self.scene_elapsed
        self.ended = True

    def _scene(self) -> Scene:
        return self.fig.scenes[self.current]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def remaining(self) -> float:
        if self._duration is None:
            return 0.0
        return max(0.0, self._duration - self.scene_elapsed)

    def _resolve(self, content: str) -> str:
        s = self._scene()
        # {elapsed}/{elapsed_ms} run with the scene only when it ticks;
        # tickless scenes show the previous scene's frozen clock (stopwatch
        # STOPPED, reaction-timer result)
        elapsed = self.scene_elapsed if s.tick else self._last_elapsed
        out = (content
               .replace("{remaining}", _fmt_clock(self.remaining()))
               .replace("{remaining_s}", str(int(math.ceil(self.remaining()))))
               .replace("{elapsed}", _fmt_clock(elapsed))
               .replace("{elapsed_ms}", str(int(elapsed * 1000)))
               .replace("{slot}", self.slots.get("", "")))
        out = SLOT_TOKEN_RE.sub(lambda m: self.slots.get(m.group(1), ""), out)
        for name, val in self.counters.items():
            out = out.replace("{count:%s}" % name, str(val))
        return contracts.clamp_text(out, MAX_TEXT_LEN)

    def frame(self) -> DisplayFrame:
        if self.ended:
            return DisplayFrame(scene=END, ended=True)
        s = self._scene()
        pulse_on = False
        pulse_color = None
        if s.pulse is not None and self._duration is not None:
            if self.remaining() <= s.pulse.window_sec:
                # square wave at rate_hz, phase-locked to the scene clock
                phase = self.scene_elapsed * s.pulse.rate_hz
                pulse_on = (int(phase * 2) % 2) == 0
                pulse_color = s.pulse.color
        cadence_phase, cadence_level = self._cadence()
        return DisplayFrame(
            scene=self.current,
            lines=[ResolvedLine(self._resolve(ln.content), ln.row,
                                ln.size, ln.color) for ln in s.lines],
            glyphs=list(s.glyphs),
            pulse_on=pulse_on,
            pulse_color=pulse_color,
            cadence_phase=cadence_phase,
            cadence_level=cadence_level,
        )

    def _cadence(self) -> tuple[str, float]:
        """The breathing envelope at the current scene time (5.1 #4): ramp in →
        hold → ramp out, cycling over the cadence period. Amplitude in 0..1."""
        cad = self._scene().cadence
        if cad is None:
            return "", 0.0
        period = cad.period()
        if period <= 0:
            return "", 0.0
        u = self.scene_elapsed % period
        if u < cad.in_s:
            return "in", round(u / cad.in_s if cad.in_s else 1.0, 3)
        if u < cad.in_s + cad.hold_s:
            return "hold", 1.0
        out = u - cad.in_s - cad.hold_s
        return "out", round(1.0 - (out / cad.out_s if cad.out_s else 1.0), 3)

    # ------------------------------------------------------------------
    # Hot-swap / revoke (mirrors the Lua stage's contract)
    # ------------------------------------------------------------------

    def swap(self, fig: Figment) -> None:
        """Replace the running figment between ticks — no reboot."""
        rng, batt = self.rng, self.battery_level
        # deliberate in-place re-init: hot-swap the running figment without
        # rebinding the interpreter object the tick loop holds.
        self.__init__(fig, rng=rng, battery_level=batt)  # type: ignore[misc]

    def revoke(self) -> None:
        """Stop and clear; the stage returns to ambient ready."""
        self.ended = True


def log_recorded(stage: "Stage", vault, figment_id: str) -> int:
    """Drain a stage's recorded emits (transitions flagged ``record: true``, 5.1
    #5) into the Vault performance log — turning a figment into an instrument that
    produces *data you keep* (batch logs, rep history, medication-taken marks).
    Returns how many lines were written; leaves the stage's buffer empty."""
    for ts, tag in stage.recorded:
        vault.record_performance(figment_id, {"emit": tag, "at": ts})
    n = len(stage.recorded)
    stage.recorded = []
    return n
