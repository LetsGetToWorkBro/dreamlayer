"""v2/playback.py — the run-through: time-folded preview of a Figment.

What you author, you watch — before it deploys, on the display it will
live on. Long stretches are folded (a 3-minute round replays in seconds
with a `⋯ 2:40 ⋯` fold marker); the interesting moments — scene entries,
pulse windows, transitions, loop closure — play at full detail.

run_through() drives the reference Stage deterministically and returns
PlaybackFrames. render_png() rasterizes a frame as the 256×256 circular
HUD card (Pillow, optional) for the phone mirror and the demo exports.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .figment import Figment, END
from .interpreter import Stage, DisplayFrame, ResolvedLine, _fmt_clock

MAX_FRAMES = 72          # a run-through is seconds long, never minutes
DETAIL_HEAD_SEC = 2      # seconds shown in full at scene entry
DETAIL_TAIL_SEC = 4      # seconds shown in full before a timeout
PULSE_SAMPLES_PER_SEC = 2


@dataclass
class PlaybackFrame:
    t_sim: float                 # simulated seconds since start
    label: str                   # "enter rolling", "fold 2:40", "pulse", …
    frame: DisplayFrame
    folded: bool = False


def _fold_frame(scene: str, folded_sec: float) -> DisplayFrame:
    return DisplayFrame(scene=scene, lines=[
        ResolvedLine(f"⋯ {_fmt_clock(folded_sec)} ⋯", row=2, size="sm",
                     color="text_secondary")])


def run_through(fig: Figment, seed: int = 7,
                inject: Optional[list[tuple[float, str]]] = None,
                max_sim_sec: float = 6 * 3600.0) -> list[PlaybackFrame]:
    """Simulate the figment and sample frames, folding dull time.

    inject: optional scripted events [(sim_t, event), …] — the run-through
    auto-fires the armed trigger if the initial scene only waits.
    """
    stage = Stage(fig, rng=random.Random(seed))
    frames: list[PlaybackFrame] = []
    inject = sorted(inject or [], key=lambda p: p[0])
    seen_scene_entries: dict[str, int] = {}

    def snap(label: str, folded: bool = False,
             frame: Optional[DisplayFrame] = None) -> None:
        if len(frames) >= MAX_FRAMES:
            return
        frames.append(PlaybackFrame(round(stage.clock, 3), label,
                                    frame or stage.frame(), folded))

    # if nothing is scripted and the initial scene only waits on events,
    # fire its first event so the run-through actually runs
    initial = fig.scenes[fig.initial]
    if not inject and not initial.timed() and initial.on:
        inject = [(0.0, sorted(initial.on)[0])]

    snap(f"enter {stage.current}")
    guard = 0
    while not stage.ended and len(frames) < MAX_FRAMES and guard < 10_000:
        guard += 1

        # deliver due scripted events
        while inject and inject[0][0] <= stage.clock + 1e-9:
            _, ev = inject.pop(0)
            before = stage.current
            stage.inject(ev)
            snap(f"{ev} → {stage.current}" if stage.current != before
                 else ev)
            if stage.ended:
                break
        if stage.ended:
            break

        scene = fig.scenes[stage.current]
        entries = seen_scene_entries.get(stage.current, 0)

        if not scene.timed():
            # event-only scene with nothing scheduled: the run-through is over
            if not inject:
                snap("waiting (event-only)")
                break
            # fast-forward to the next scripted event
            stage.step(max(inject[0][0] - stage.clock, 0.001))
            continue

        remaining = stage.remaining()
        pulse_window = scene.pulse.window_sec if scene.pulse else 0.0
        head = min(DETAIL_HEAD_SEC, remaining)
        tail = min(max(DETAIL_TAIL_SEC, pulse_window), remaining)

        # head detail
        for _ in range(int(head)):
            if stage.remaining() <= tail:
                break
            stage.step(1.0)
            snap(f"{stage.current} {stage.frame().lines[0].text if stage.frame().lines else ''}".strip())

        # fold the dull middle
        dull = stage.remaining() - tail
        if dull > 1.0:
            stage.step(dull)
            snap(f"fold {_fmt_clock(dull)}", folded=True,
                 frame=_fold_frame(stage.current, dull))

        # tail detail (samples pulse phases at 2/sec)
        prev_scene = stage.current
        step = 1.0 / PULSE_SAMPLES_PER_SEC if scene.pulse else 1.0
        re_entered = False
        while not stage.ended:
            prev_elapsed = stage.scene_elapsed
            stage.step(step)
            re_entered = (stage.current == prev_scene
                          and stage.scene_elapsed < prev_elapsed)
            if stage.current != prev_scene or re_entered:
                break
            f = stage.frame()
            snap("pulse" if f.pulse_on else prev_scene, frame=f)
            if len(frames) >= MAX_FRAMES:
                break

        if stage.ended:
            snap("end")
            break
        if stage.current != prev_scene or re_entered:
            n = seen_scene_entries.get(stage.current, 0) + 1
            seen_scene_entries[stage.current] = n
            snap(f"enter {stage.current}")
            if n >= 2 or re_entered:
                snap("loop closes — run-through complete")
                break
        if stage.clock > max_sim_sec:
            break

    return frames


# ---------------------------------------------------------------------------
# Rasterization (Pillow optional) — 256×256 circular HUD card
# ---------------------------------------------------------------------------

# semantic tokens → hex (docs/HUD_DESIGN_SYSTEM.md)
TOKEN_HEX = {
    "background": 0x000000, "surface": 0x0E1416,
    "text_primary": 0xFFFFFF, "text_secondary": 0x8A9BA3,
    "accent_memory": 0x2FD4C4, "accent_attention": 0xFF6B5E,
    "accent_success": 0x56D364, "accent_error": 0xFF5C5C,
    "border_subtle": 0x1F2A2E, "status_paused": 0x6B7A82,
}

_SIZE_PX = {"sm": 12, "md": 18, "lg": 30}
DISPLAY_PX = 256
SAFE_INSET = 16


def _rgb(token: str) -> tuple[int, int, int]:
    v = TOKEN_HEX.get(token, 0xFFFFFF)
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


def render_png(frame: DisplayFrame, path: str) -> Optional[str]:
    """Draw one frame as the circular HUD card. Returns path, or None
    when Pillow is unavailable (headless CI)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    img = Image.new("RGB", (DISPLAY_PX, DISPLAY_PX), _rgb("background"))
    draw = ImageDraw.Draw(img)

    # circular bezel
    draw.ellipse([1, 1, DISPLAY_PX - 2, DISPLAY_PX - 2],
                 outline=_rgb("border_subtle"), width=2)

    if frame.pulse_on and frame.pulse_color:
        draw.ellipse([5, 5, DISPLAY_PX - 6, DISPLAY_PX - 6],
                     outline=_rgb(frame.pulse_color), width=4)

    if frame.ended:
        draw.text((DISPLAY_PX // 2, DISPLAY_PX // 2), "◦",
                  fill=_rgb("status_paused"), anchor="mm")
    else:
        rows = 5
        usable = DISPLAY_PX - 2 * (SAFE_INSET + 24)
        for ln in frame.lines:
            y = SAFE_INSET + 24 + usable * (ln.row + 0.5) / rows
            size = _SIZE_PX.get(ln.size, 18)
            font = _font(size)
            draw.text((DISPLAY_PX // 2, y), ln.text,
                      fill=_rgb(ln.color), anchor="mm", font=font)

    img.save(path)
    return path


def _font(size: int):
    from PIL import ImageFont
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def transcript(frames: list[PlaybackFrame]) -> str:
    """Text form of a run-through (tests, demo logs)."""
    out = []
    for pf in frames:
        mark = "⋯" if pf.folded else ("●" if pf.frame.pulse_on else " ")
        body = " / ".join(ln.text for ln in sorted(pf.frame.lines,
                                                   key=lambda l: l.row))
        out.append(f"{pf.t_sim:8.1f}s {mark} [{pf.label}] {body}")
    return "\n".join(out)
