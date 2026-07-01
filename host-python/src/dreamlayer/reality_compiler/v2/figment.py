"""v2/figment.py — the Figment: a total, budgeted, signable behavior machine.

A Figment is what a rehearsed behavior compiles to, and the only thing the
on-device stage will run. It is data, never code:

  - a finite set of Scenes (max 32)
  - each Scene shows up to 5 short text lines and may exit on a timer
    (>= 0.5 s, so time-consuming by construction) or on an external event
  - bounded, saturating Counters (max 8)
  - an optional PulseSpec per scene (final-window emphasis, rate-capped)
  - transitions may carry counter ops and rate-limited emits to the host

There are no expressions, no user-defined loops, and no zero-time cycles:
every timed exit consumes at least MIN_SCENE_SEC of wall time and every
other exit consumes an external event. Worst-case cost is therefore
computable statically (see budgets.verify) before a Figment is signed.

Serialization is canonical JSON (sorted keys, compact separators) so that
signatures are stable across host and device.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Hard limits (mirrored by the Lua stage's dynamic clamps)
# ---------------------------------------------------------------------------

MAX_SCENES        = 32
MAX_COUNTERS      = 8
MAX_LINES         = 5      # HUD rule: max ~5 short lines
MAX_TEXT_LEN      = 24     # chars per line on the 256px circular display
MAX_COUNTER_OPS   = 4      # per transition
MAX_BRANCHES      = 4      # guarded timeout branches per scene
MAX_PULSE_HZ      = 4.0    # display breathe cap
MIN_SCENE_SEC     = 0.5    # every timed exit consumes at least this
MAX_SCENE_SEC     = 24 * 3600.0
EMIT_BURST        = 5      # BLE token bucket capacity
EMIT_REFILL_PER_S = 1.0    # BLE token bucket refill
MAX_EMIT_TAG_LEN  = 16
MAX_NAME_LEN      = 40

END  = "@end"    # transition target: figment finishes, stage goes ambient
SELF = "@self"   # transition target: re-enter current scene (resets clock)

# Semantic color tokens (docs/HUD_DESIGN_SYSTEM.md) — the only colors a
# figment may name.
COLOR_TOKENS = frozenset({
    "background", "surface", "text_primary", "text_secondary",
    "accent_memory", "accent_attention", "accent_success", "accent_error",
    "border_subtle", "status_paused",
})

SIZES = frozenset({"sm", "md", "lg"})

# Events a scene may listen for. "ble:<n>" (single byte code) and
# "text" (host-pushed string into the slot) are also accepted.
BASE_EVENTS = frozenset({"single", "double", "long", "imu_tap",
                         "ble", "text", "battery_low"})

TICKS = frozenset({"countdown", "countup"})


class FigmentError(ValueError):
    """Raised when a figment is structurally malformed (pre-verify)."""


def _valid_event(name: str) -> bool:
    if name in BASE_EVENTS:
        return True
    if name.startswith("ble:"):
        code = name[4:]
        return code.isdigit() and 0 <= int(code) <= 255
    return False


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------

@dataclass
class TextLine:
    """One display line. `content` may use the tokens
    {remaining} {remaining_s} {elapsed} {elapsed_ms} {count:<name>} {slot}."""
    content: str
    row: int = 0                 # 0 (top) .. MAX_LINES-1
    size: str = "md"
    color: str = "text_primary"

    def to_dict(self) -> dict:
        return {"content": self.content, "row": self.row,
                "size": self.size, "color": self.color}

    @staticmethod
    def from_dict(d: dict) -> "TextLine":
        return TextLine(d["content"], d.get("row", 0),
                        d.get("size", "md"), d.get("color", "text_primary"))


@dataclass
class PulseSpec:
    """Final-window emphasis: breathe `color` at `rate_hz` for the last
    `window_sec` seconds of the scene's duration."""
    window_sec: float
    color: str = "accent_attention"
    rate_hz: float = 2.0

    def to_dict(self) -> dict:
        return {"window_sec": self.window_sec, "color": self.color,
                "rate_hz": self.rate_hz}

    @staticmethod
    def from_dict(d: dict) -> "PulseSpec":
        return PulseSpec(d["window_sec"], d.get("color", "accent_attention"),
                         d.get("rate_hz", 2.0))


@dataclass
class CounterDecl:
    """A bounded integer. All ops saturate at [lo, hi]."""
    name: str
    start: int = 0
    lo: int = 0
    hi: int = 9999

    def to_dict(self) -> dict:
        return {"name": self.name, "start": self.start,
                "lo": self.lo, "hi": self.hi}

    @staticmethod
    def from_dict(d: dict) -> "CounterDecl":
        return CounterDecl(d["name"], d.get("start", 0),
                           d.get("lo", 0), d.get("hi", 9999))


@dataclass
class CounterOp:
    counter: str
    op: str = "inc"              # inc | dec | set
    amount: int = 1

    def to_dict(self) -> dict:
        return {"counter": self.counter, "op": self.op, "amount": self.amount}

    @staticmethod
    def from_dict(d: dict) -> "CounterOp":
        return CounterOp(d["counter"], d.get("op", "inc"), d.get("amount", 1))


@dataclass
class Guard:
    """Counter comparison gating a timeout branch."""
    counter: str
    cmp: str                     # ge | le | eq
    value: int

    def to_dict(self) -> dict:
        return {"counter": self.counter, "cmp": self.cmp, "value": self.value}

    @staticmethod
    def from_dict(d: dict) -> "Guard":
        return Guard(d["counter"], d["cmp"], d["value"])


@dataclass
class Transition:
    target: str                                  # scene id | @end | @self
    counter_ops: list[CounterOp] = field(default_factory=list)
    emit: Optional[str] = None                   # short tag sent to host
    when: Optional[Guard] = None                 # only for timeout branches

    def to_dict(self) -> dict:
        d: dict = {"target": self.target}
        if self.counter_ops:
            d["counter_ops"] = [o.to_dict() for o in self.counter_ops]
        if self.emit is not None:
            d["emit"] = self.emit
        if self.when is not None:
            d["when"] = self.when.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict) -> "Transition":
        return Transition(
            d["target"],
            [CounterOp.from_dict(o) for o in d.get("counter_ops", [])],
            d.get("emit"),
            Guard.from_dict(d["when"]) if d.get("when") else None,
        )


@dataclass
class Scene:
    id: str
    lines: list[TextLine] = field(default_factory=list)
    duration_sec: Optional[float] = None         # timed exit after this
    duration_range: Optional[tuple[float, float]] = None  # random (react timer)
    tick: Optional[str] = None                   # countdown | countup | None
    on_timeout: list[Transition] = field(default_factory=list)
    on: dict[str, Transition] = field(default_factory=dict)
    pulse: Optional[PulseSpec] = None

    def timed(self) -> bool:
        return self.duration_sec is not None or self.duration_range is not None

    def min_duration(self) -> float:
        if self.duration_range is not None:
            return self.duration_range[0]
        return self.duration_sec if self.duration_sec is not None else 0.0

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "lines": [ln.to_dict() for ln in self.lines]}
        if self.duration_sec is not None:
            d["duration_sec"] = self.duration_sec
        if self.duration_range is not None:
            d["duration_range"] = list(self.duration_range)
        if self.tick:
            d["tick"] = self.tick
        if self.on_timeout:
            d["on_timeout"] = [t.to_dict() for t in self.on_timeout]
        if self.on:
            d["on"] = {k: v.to_dict() for k, v in sorted(self.on.items())}
        if self.pulse:
            d["pulse"] = self.pulse.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict) -> "Scene":
        rng = d.get("duration_range")
        return Scene(
            id=d["id"],
            lines=[TextLine.from_dict(x) for x in d.get("lines", [])],
            duration_sec=d.get("duration_sec"),
            duration_range=(rng[0], rng[1]) if rng else None,
            tick=d.get("tick"),
            on_timeout=[Transition.from_dict(t) for t in d.get("on_timeout", [])],
            on={k: Transition.from_dict(v) for k, v in d.get("on", {}).items()},
            pulse=PulseSpec.from_dict(d["pulse"]) if d.get("pulse") else None,
        )


# ---------------------------------------------------------------------------
# Figment
# ---------------------------------------------------------------------------

@dataclass
class Figment:
    name: str
    initial: str
    scenes: dict[str, Scene] = field(default_factory=dict)
    counters: dict[str, CounterDecl] = field(default_factory=dict)
    battery_below: Optional[int] = None          # fires "battery_low" events
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    version: int = 2
    meta: dict = field(default_factory=dict)     # origin trace, created_at…

    # -- structure -----------------------------------------------------

    def add_scene(self, scene: Scene) -> Scene:
        if scene.id in self.scenes:
            raise FigmentError(f"duplicate scene id {scene.id!r}")
        self.scenes[scene.id] = scene
        return scene

    def add_counter(self, decl: CounterDecl) -> CounterDecl:
        if decl.name in self.counters:
            raise FigmentError(f"duplicate counter {decl.name!r}")
        self.counters[decl.name] = decl
        return decl

    # -- serialization ---------------------------------------------------

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "initial": self.initial,
            "scenes": {sid: s.to_dict() for sid, s in sorted(self.scenes.items())},
        }
        if self.counters:
            d["counters"] = {n: c.to_dict() for n, c in sorted(self.counters.items())}
        if self.battery_below is not None:
            d["battery_below"] = self.battery_below
        if self.meta:
            d["meta"] = self.meta
        return d

    @staticmethod
    def from_dict(d: dict) -> "Figment":
        f = Figment(
            name=d["name"],
            initial=d["initial"],
            id=d["id"],
            version=d.get("version", 2),
            battery_below=d.get("battery_below"),
            meta=d.get("meta", {}),
        )
        for sid, sd in d.get("scenes", {}).items():
            f.scenes[sid] = Scene.from_dict(sd)
        for name, cd in d.get("counters", {}).items():
            f.counters[name] = CounterDecl.from_dict(cd)
        return f

    def canonical_json(self) -> str:
        """Stable byte-for-byte form — the thing that gets signed."""
        return json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True)

    # -- inspection --------------------------------------------------------

    def describe(self) -> str:
        """Plain-words reading of the machine, for the Repertoire card."""
        lines = [f"{self.name} — {len(self.scenes)} scenes"]
        for sid, s in self.scenes.items():
            bits = []
            if s.timed():
                if s.duration_range:
                    bits.append(f"{s.duration_range[0]:g}-{s.duration_range[1]:g}s")
                else:
                    bits.append(f"{s.duration_sec:g}s")
            if s.tick:
                bits.append(s.tick)
            if s.pulse:
                bits.append(f"pulse last {s.pulse.window_sec:g}s")
            for ev in sorted(s.on):
                bits.append(f"on {ev} → {s.on[ev].target}")
            marker = "▶ " if sid == self.initial else "  "
            lines.append(f"{marker}{sid}: " + (", ".join(bits) or "static"))
        return "\n".join(lines)
