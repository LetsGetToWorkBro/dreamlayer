"""v2/budgets.py — static verification: no Figment ships without a proof.

verify() checks every constraint the stage relies on, *before* signing:

  structural   — scene/counter/line/text-length caps, targets resolve,
                 events are known, colors are palette tokens
  temporal     — every timed exit >= MIN_SCENE_SEC, pulse window fits the
                 scene, pulse rate <= MAX_PULSE_HZ  (display budget)
  livelock     — no cycle in the timeout graph with zero minimum duration
                 (structurally impossible given MIN_SCENE_SEC, asserted
                 anyway as defense in depth)
  BLE budget   — for every cycle in the timeout graph, seconds-around-cycle
                 >= emits-around-cycle / EMIT_REFILL_PER_S (sustained rate),
                 so autonomous emit floods are unrepresentable
  reachability — unreachable scenes are a warning (dead weight on device)

The result is a BudgetReport: a machine-checkable proof object attached to
the figment before it is signed. Violations carry the scene id and, when
the figment came from a rehearsal, the beat index that produced the scene —
teach.py turns those into user-language cards.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .figment import (
    Figment, Scene, Transition, FigmentError,
    MAX_SCENES, MAX_COUNTERS, MAX_LINES, MAX_TEXT_LEN, MAX_COUNTER_OPS,
    MAX_BRANCHES, MAX_PULSE_HZ, MIN_SCENE_SEC, MAX_SCENE_SEC,
    EMIT_REFILL_PER_S, MAX_EMIT_TAG_LEN, MAX_NAME_LEN,
    MAX_GLYPHS, MAX_GLYPH_POINTS, MAX_SLOTS, named_slots,
    COLOR_TOKENS, SIZES, TICKS, END, SELF, _valid_event,
)


@dataclass
class Violation:
    code: str            # stable machine code, e.g. "pulse_rate"
    message: str         # engineer-facing
    scene: Optional[str] = None
    beat: Optional[int] = None   # rehearsal beat index, if known

    def __str__(self) -> str:
        where = f" [scene {self.scene}]" if self.scene else ""
        return f"{self.code}{where}: {self.message}"


@dataclass
class BudgetReport:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    warnings: list[Violation] = field(default_factory=list)
    # proof numbers, for the Repertoire inspector
    worst_display_hz: float = 0.0
    worst_emit_per_sec: float = 0.0
    scene_count: int = 0

    def __str__(self) -> str:
        head = "BUDGETS OK" if self.ok else "BUDGETS VIOLATED"
        parts = [f"[{head}] scenes={self.scene_count} "
                 f"display<={self.worst_display_hz:g}Hz "
                 f"emit<={self.worst_emit_per_sec:g}/s"]
        parts += [f"  ✗ {v}" for v in self.violations]
        parts += [f"  ⚠ {w}" for w in self.warnings]
        return "\n".join(parts)


def _beat_of(fig: Figment, scene_id: str) -> Optional[int]:
    return fig.meta.get("scene_beats", {}).get(scene_id)


def verify(fig: Figment) -> BudgetReport:
    """Prove the figment fits the constraint envelope. Never raises."""
    v: list[Violation] = []
    warn: list[Violation] = []

    def bad(code: str, msg: str, scene: Optional[str] = None) -> None:
        v.append(Violation(code, msg, scene,
                           _beat_of(fig, scene) if scene else None))

    # -- structural ---------------------------------------------------------
    if not fig.name or len(fig.name) > MAX_NAME_LEN:
        bad("name", f"name must be 1..{MAX_NAME_LEN} chars")
    if len(fig.scenes) == 0:
        bad("empty", "figment has no scenes")
    if len(fig.scenes) > MAX_SCENES:
        bad("scene_count", f"{len(fig.scenes)} scenes > max {MAX_SCENES}")
    if len(fig.counters) > MAX_COUNTERS:
        bad("counter_count", f"{len(fig.counters)} counters > max {MAX_COUNTERS}")
    slots = named_slots(fig)
    if len(slots) > MAX_SLOTS:
        bad("slot_count", f"{len(slots)} named slots > max {MAX_SLOTS}")
    for name in slots:
        if len(name) > MAX_NAME_LEN:
            bad("slot_name", f"slot name {name!r} > {MAX_NAME_LEN} chars")
    if fig.initial not in fig.scenes:
        bad("initial", f"initial scene {fig.initial!r} does not exist")
    if fig.battery_below is not None and not 1 <= fig.battery_below <= 99:
        bad("battery", "battery_below must be in [1, 99]")

    def check_transition(sid: str, t: Transition, timeout: bool) -> None:
        if t.target not in (END, SELF) and t.target not in fig.scenes:
            bad("target", f"transition to unknown scene {t.target!r}", sid)
        if len(t.counter_ops) > MAX_COUNTER_OPS:
            bad("counter_ops", f"{len(t.counter_ops)} counter ops > max "
                f"{MAX_COUNTER_OPS}", sid)
        for op in t.counter_ops:
            if op.counter not in fig.counters:
                bad("counter", f"op on undeclared counter {op.counter!r}", sid)
            if op.op not in ("inc", "dec", "set"):
                bad("counter", f"unknown counter op {op.op!r}", sid)
        if t.emit is not None and (not t.emit or len(t.emit) > MAX_EMIT_TAG_LEN):
            bad("emit_tag", f"emit tag must be 1..{MAX_EMIT_TAG_LEN} chars", sid)
        if t.when is not None:
            if not timeout:
                bad("guard", "guards are only allowed on timeout branches", sid)
            elif t.when.counter not in fig.counters:
                bad("guard", f"guard on undeclared counter {t.when.counter!r}", sid)
            elif t.when.cmp not in ("ge", "le", "eq"):
                bad("guard", f"unknown comparison {t.when.cmp!r}", sid)

    for sid, s in fig.scenes.items():
        if len(s.lines) > MAX_LINES:
            bad("lines", f"{len(s.lines)} lines > max {MAX_LINES}", sid)
        rows_seen: set[int] = set()
        for ln in s.lines:
            if len(ln.content) > MAX_TEXT_LEN:
                bad("text_len", f"line {ln.content!r} > {MAX_TEXT_LEN} chars", sid)
            if ln.row < 0 or ln.row >= MAX_LINES:
                bad("row", f"row {ln.row} out of range", sid)
            elif ln.row in rows_seen:
                bad("row", f"two lines on row {ln.row}", sid)
            rows_seen.add(ln.row)
            if ln.color not in COLOR_TOKENS:
                bad("color", f"{ln.color!r} is not a palette token", sid)
            if ln.size not in SIZES:
                bad("size", f"unknown size {ln.size!r}", sid)

        # -- temporal
        if s.duration_sec is not None and s.duration_range is not None:
            bad("duration", "scene has both fixed and random duration", sid)
        if s.duration_sec is not None and not (
                MIN_SCENE_SEC <= s.duration_sec <= MAX_SCENE_SEC):
            bad("duration", f"duration {s.duration_sec}s outside "
                f"[{MIN_SCENE_SEC}, {MAX_SCENE_SEC}]s", sid)
        if s.duration_range is not None:
            lo, hi = s.duration_range
            if not (MIN_SCENE_SEC <= lo <= hi <= MAX_SCENE_SEC):
                bad("duration", f"random range [{lo}, {hi}]s invalid", sid)
        if s.on_timeout and not s.timed():
            bad("timeout", "on_timeout without a duration", sid)
        if s.timed() and not s.on_timeout:
            bad("timeout", "timed scene has no timeout transition", sid)
        if len(s.on_timeout) > MAX_BRANCHES:
            bad("branches", f"{len(s.on_timeout)} timeout branches > max "
                f"{MAX_BRANCHES}", sid)
        if s.on_timeout and s.on_timeout[-1].when is not None:
            bad("branches", "last timeout branch must be unguarded (default)", sid)
        if s.tick is not None and s.tick not in TICKS:
            bad("tick", f"unknown tick {s.tick!r}", sid)
        if s.tick == "countdown" and not s.timed():
            bad("tick", "countdown tick on an untimed scene", sid)

        # -- pulse (display budget)
        if s.pulse is not None:
            if not s.timed():
                bad("pulse", "pulse on an untimed scene", sid)
            else:
                if s.pulse.rate_hz <= 0 or s.pulse.rate_hz > MAX_PULSE_HZ:
                    bad("pulse_rate", f"pulse {s.pulse.rate_hz}Hz > max "
                        f"{MAX_PULSE_HZ}Hz — the display budget", sid)
                if s.pulse.window_sec <= 0 or s.pulse.window_sec > s.min_duration():
                    bad("pulse", f"pulse window {s.pulse.window_sec}s exceeds "
                        "scene duration", sid)
            if s.pulse.color not in COLOR_TOKENS:
                bad("color", f"pulse color {s.pulse.color!r} is not a token", sid)

        # -- paint layer: bounded strokes, palette colors, in-frame coords
        if len(s.glyphs) > MAX_GLYPHS:
            bad("glyphs", f"{len(s.glyphs)} strokes > max {MAX_GLYPHS}", sid)
        for gi, g in enumerate(s.glyphs):
            if not (2 <= len(g.points) <= MAX_GLYPH_POINTS):
                bad("glyph_points", f"stroke {gi} has {len(g.points)} points "
                    f"(need 2..{MAX_GLYPH_POINTS})", sid)
            for x, y in g.points:
                if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                    bad("glyph_coord", f"stroke {gi} point ({x:g},{y:g}) "
                        "outside the [0,1] display", sid)
                    break
            if g.color not in COLOR_TOKENS:
                bad("color", f"stroke {gi} color {g.color!r} is not a token", sid)
            if g.width not in SIZES:
                bad("glyph_width", f"stroke {gi} width {g.width!r} unknown", sid)

        # -- cadence (5.1 #4): a breath must be slow, non-negative, bounded
        if s.cadence is not None:
            cad = s.cadence
            if min(cad.in_s, cad.hold_s, cad.out_s) < 0:
                bad("cadence", "cadence segments must be non-negative", sid)
            period = cad.period()
            if not (MIN_SCENE_SEC <= period <= MAX_SCENE_SEC):
                bad("cadence", f"cadence period {period}s outside "
                    f"[{MIN_SCENE_SEC}, {MAX_SCENE_SEC}]s", sid)

        # -- events
        for ev, t in s.on.items():
            if not _valid_event(ev):
                bad("event", f"unknown event {ev!r}", sid)
            check_transition(sid, t, timeout=False)
        for t in s.on_timeout:
            check_transition(sid, t, timeout=True)

    if fig.battery_below is not None:
        if not any("battery_low" in s.on for s in fig.scenes.values()):
            warn.append(Violation("battery", "battery_below set but no scene "
                                  "listens for battery_low"))

    # -- cycle analysis over the timeout graph ------------------------------
    # Event edges consume external events, so only autonomous (timeout)
    # cycles can loop or emit without the user. Enumerate them.
    worst_emit = 0.0
    if not v:  # graph analysis needs a structurally sound figment
        worst_emit = _cycle_analysis(fig, v)

    # -- reachability --------------------------------------------------------
    if fig.initial in fig.scenes:
        seen: set[str] = set()
        stack = [fig.initial]
        while stack:
            sid = stack.pop()
            if sid in seen or sid not in fig.scenes:
                continue
            seen.add(sid)
            s = fig.scenes[sid]
            for t in list(s.on.values()) + s.on_timeout:
                if t.target not in (END, SELF):
                    stack.append(t.target)
        for sid in fig.scenes:
            if sid not in seen:
                warn.append(Violation("unreachable",
                                      f"scene {sid!r} is unreachable", sid))

    worst_display = 1.0  # 1 Hz tick baseline
    for s in fig.scenes.values():
        if s.pulse:
            worst_display = max(worst_display, s.pulse.rate_hz)

    return BudgetReport(
        ok=not v,
        violations=v,
        warnings=warn,
        worst_display_hz=worst_display,
        worst_emit_per_sec=worst_emit,
        scene_count=len(fig.scenes),
    )


def _cycle_analysis(fig: Figment, v: list[Violation]) -> float:
    """Enumerate simple cycles in the timeout graph; enforce time >= emits.

    Returns the worst sustained autonomous emit rate found (emits/sec)."""
    # adjacency over timeout edges only (SELF is a 1-node cycle)
    edges: dict[str, list[tuple[str, float, int]]] = {}
    for sid, s in fig.scenes.items():
        if not s.timed():
            continue
        dur = s.min_duration()
        for t in s.on_timeout:
            target = sid if t.target == SELF else t.target
            if target == END:
                continue
            emits = 1 if t.emit is not None else 0
            edges.setdefault(sid, []).append((target, dur, emits))

    worst_rate = 0.0
    order = sorted(fig.scenes)

    def dfs(start: str, node: str, path: list[str],
            secs: float, emits: int) -> None:
        nonlocal worst_rate
        for target, dur, e in edges.get(node, []):
            if target == start:
                total_secs, total_emits = secs + dur, emits + e
                if total_secs <= 0:
                    v.append(Violation("livelock",
                                       "zero-time autonomous cycle through "
                                       + " → ".join(path + [start]),
                                       start, _beat_of(fig, start)))
                elif total_emits:
                    rate = total_emits / total_secs
                    worst_rate = max(worst_rate, rate)
                    if rate > EMIT_REFILL_PER_S:
                        v.append(Violation(
                            "ble_flood",
                            f"autonomous cycle {' → '.join(path + [start])} "
                            f"emits {rate:.2f}/s > budget "
                            f"{EMIT_REFILL_PER_S:g}/s",
                            start, _beat_of(fig, start)))
            # only expand to nodes after start in canonical order, so each
            # simple cycle is found exactly once (rooted at its least node)
            elif target not in path and target > start:
                dfs(start, target, path + [target], secs + dur, emits + e)

    for start in order:
        dfs(start, start, [start], 0.0, 0)
    return worst_rate


def verify_or_raise(fig: Figment) -> BudgetReport:
    report = verify(fig)
    if not report.ok:
        raise FigmentError(str(report))
    return report
