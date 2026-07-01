"""v2/choreographer.py — beat trace → Figment inference.

The choreographer generalizes one performed round into a machine:

  strong tap before content     → trigger (armed scene waits for it)
  "label - three minutes"       → timed scene, countdown, folded 180 s
  short real dwell              → literal timed scene
  "pulse" / "warn me"           → final-window emphasis on the last
                                  timed scene
  "count this"                  → bounded counter bound to the trigger tap
  "send <tag>"                  → emit on the current scene's exit
  "again" / "again N times"     → cycle back to the first performed scene
                                  (guarded exit after N)
  "until I <gesture>"           → event exit from every running scene
  "show <text>"                 → extra static line / static scene

Inference is deliberately conservative: anything it cannot place raises
InferenceError with the beat index, which teach.py turns into a card. The
figment's meta carries scene→beat provenance so budget violations can
point back at the exact beat that caused them.
"""
from __future__ import annotations

import re
from typing import Optional

from .figment import (
    Figment, Scene, TextLine, PulseSpec, CounterDecl, CounterOp,
    Guard, Transition, END, MAX_LINES,
)
from .rehearsal import Beat


class InferenceError(ValueError):
    def __init__(self, code: str, message: str, beat: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.beat = beat


_TAP_EVENT = {"tap": "single", "double_tap": "double", "long_press": "long"}


def _slug(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "scene"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}_{n}", n + 1
    return slug


class Choreographer:
    def infer(self, beats: list[Beat], name: str = "Rehearsed behavior") -> Figment:
        fig = Figment(name=name, initial="armed")
        scene_beats: dict[str, int] = {}

        trigger: Optional[str] = None
        trigger_beat: Optional[int] = None
        performed: list[str] = []           # timed/static scenes in order
        loop: Optional[tuple[Optional[int], int]] = None  # (times, beat)
        until: Optional[str] = None
        counter_label: Optional[str] = None
        pending_emit: Optional[tuple[str, Optional[float], int]] = None

        def last_scene() -> Optional[Scene]:
            return fig.scenes[performed[-1]] if performed else None

        def new_scene(label: str, beat: Beat) -> Scene:
            sid = _slug(label, set(fig.scenes))
            scene = fig.add_scene(Scene(id=sid))
            scene_beats[sid] = beat.index
            performed.append(sid)
            return scene

        for beat in beats:
            kind = beat.kind
            if kind in _TAP_EVENT:
                if not performed:
                    # a tap before any content is the trigger
                    trigger, trigger_beat = _TAP_EVENT[kind], beat.index
                # taps after content are counted only via a "count" mark
                continue

            if kind == "dwell":
                scene = new_scene("moment", beat)
                scene.duration_sec = max(0.5, float(beat.seconds or 0.5))
                scene.lines = [TextLine("{remaining_s}", row=1, size="lg")]
                continue

            if kind != "say":
                continue
            tag = beat.parsed[0]

            if tag == "duration":
                _, label, secs = beat.parsed
                if secs < 0.5:
                    raise InferenceError(
                        "too_short",
                        f"a {secs:g}s stretch is shorter than one breath "
                        "(0.5s minimum)", beat.index)
                scene = new_scene(label or "round", beat)
                scene.duration_sec = float(secs)
                scene.tick = "countdown"
                lines = []
                if label:
                    lines.append(TextLine(label.upper()[:24], row=0,
                                          size="sm", color="text_secondary"))
                lines.append(TextLine("{remaining}", row=1, size="lg"))
                scene.lines = lines

            elif tag in ("pulse", "warn"):
                scene = last_scene()
                if scene is None or not scene.timed():
                    raise InferenceError(
                        "pulse_without_time",
                        "a pulse needs a stretch of time before it — "
                        "speak a duration first", beat.index)
                window = min(float(beat.parsed[1]), scene.duration_sec)
                rate = float(beat.parsed[2]) if tag == "pulse" else 1.0
                color = "accent_attention" if tag == "pulse" else "accent_error"
                scene.pulse = PulseSpec(window_sec=window, color=color,
                                        rate_hz=rate)
                scene_beats.setdefault(scene.id, beat.index)
                # provenance: the pulse beat owns budget errors on this scene
                scene_beats[scene.id] = beat.index

            elif tag == "count":
                counter_label = beat.parsed[1] or "count"
                fig.add_counter(CounterDecl(name="count", start=0))

            elif tag == "emit":
                _, emit_tag, per_second = beat.parsed
                pending_emit = (emit_tag, per_second, beat.index)

            elif tag == "loop":
                loop = (beat.parsed[1], beat.index)

            elif tag == "until":
                until = beat.parsed[1]

            elif tag == "show":
                text = beat.parsed[1]
                scene = last_scene()
                if scene is not None and len(scene.lines) < MAX_LINES:
                    rows = {ln.row for ln in scene.lines}
                    row = next(r for r in range(MAX_LINES) if r not in rows)
                    scene.lines.append(TextLine(text, row=row, size="md",
                                                color="text_secondary"))
                else:
                    scene = new_scene(text, beat)
                    scene.duration_sec = 3.0
                    scene.lines = [TextLine(text, row=1, size="lg")]

            elif tag == "label":
                # bare words: keep as the name if nothing is on stage yet
                if not performed and beat.text:
                    fig.name = beat.text[:40]

        if not performed:
            raise InferenceError(
                "empty", "the stage saw no beats it could keep — "
                "speak a duration or dwell a moment", None)

        # ---- wire the machine --------------------------------------------
        first = performed[0]

        # armed scene: waits for the trigger (or auto-runs if none)
        armed = fig.add_scene(Scene(id="armed"))
        if trigger:
            hint = {"single": "tap: start", "double": "double-tap: start",
                    "long": "hold: start"}[trigger]
            armed.lines = [
                TextLine(fig.name.upper()[:24], row=0, size="sm",
                         color="text_secondary"),
                TextLine("READY", row=1, size="lg"),
                TextLine(hint, row=3, size="sm", color="text_secondary"),
            ]
            armed.on[trigger] = Transition(target=first)
            if trigger_beat is not None:
                scene_beats["armed"] = trigger_beat
        else:
            armed.duration_sec = 0.5
            armed.on_timeout = [Transition(target=first)]
            armed.lines = [TextLine(fig.name.upper()[:24], row=1, size="sm",
                                    color="text_secondary")]

        # counter bound to the trigger tap ("count this")
        if counter_label is not None:
            scene = fig.scenes[first]
            ev = trigger or "single"
            scene.on[ev] = Transition(target="@self",
                                      counter_ops=[CounterOp("count", "inc", 1)])
            rows = {ln.row for ln in scene.lines}
            row = next(r for r in range(MAX_LINES) if r not in rows)
            scene.lines.append(TextLine("{count:count} " + counter_label[:10],
                                        row=row, size="md",
                                        color="accent_memory"))

        # chain performed scenes, then loop or end
        for i, sid in enumerate(performed):
            scene = fig.scenes[sid]
            if not scene.timed():
                continue
            if scene.on_timeout:
                continue
            nxt = performed[i + 1] if i + 1 < len(performed) else None
            if nxt is not None:
                scene.on_timeout = [Transition(target=nxt)]
            elif loop is not None:
                times, loop_beat = loop
                back = Transition(target=first)
                if pending_emit:
                    back.emit = pending_emit[0]
                if times:
                    fig.add_counter(CounterDecl(name="round", start=1,
                                                lo=0, hi=max(times, 1)))
                    scene.on_timeout = [
                        Transition(target=END,
                                   when=Guard("round", "ge", times)),
                        Transition(target=first,
                                   counter_ops=[CounterOp("round", "inc", 1)],
                                   emit=back.emit),
                    ]
                    # show round progress on the first scene
                    fscene = fig.scenes[first]
                    rows = {ln.row for ln in fscene.lines}
                    if len(fscene.lines) < MAX_LINES:
                        row = next(r for r in range(MAX_LINES)
                                   if r not in rows)
                        fscene.lines.append(TextLine(
                            "{count:round}/%d" % times, row=row, size="sm",
                            color="text_secondary"))
                else:
                    scene.on_timeout = [back]
                scene_beats.setdefault(sid, loop_beat)
            else:
                done = Transition(target=END)
                if pending_emit:
                    done.emit = pending_emit[0]
                scene.on_timeout = [done]

        # emit marks with an explicit rate become autonomous emit cycles —
        # represent honestly so the verifier can judge them
        if pending_emit and pending_emit[1]:
            tag_, per_second, beat_idx = pending_emit
            period = 1.0 / per_second
            sid = _slug("beacon", set(fig.scenes))
            beacon = fig.add_scene(Scene(
                id=sid,
                duration_sec=max(period, 0.5),
                lines=[TextLine("sending " + tag_, row=1, size="sm",
                                color="text_secondary")],
                on_timeout=[Transition(target="@self", emit=tag_)],
            ))
            scene_beats[sid] = beat_idx
            last = fig.scenes[performed[-1]]
            if not last.timed() and not last.on:
                last.duration_sec = 1.0
                last.on_timeout = [Transition(target=sid)]
            else:
                armed.on.setdefault("long", Transition(target=sid))

        # "until I <gesture>": every running scene exits on it
        if until:
            for sid in performed:
                fig.scenes[sid].on.setdefault(until, Transition(target=END))

        fig.meta["scene_beats"] = scene_beats
        fig.meta["origin"] = "rehearsal"
        return fig
