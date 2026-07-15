"""v2/compat.py — every v1 behavior, lifted into a Figment.

Backward compat is a hard requirement: a v1 template dropped into v2
compiles and runs identically. lift() maps each of the 15 v1
BehaviorIntent dataclasses to a Figment preserving its semantics —
durations, triggers, labels, warning colors, counters.

v2 is a strict superset of v1 here: five v1 intents (overtime_timer,
next_class, text_subtitles, gesture_repeater, speaker_indicator) had no
registered template in v1's library and could never actually compile;
all fifteen lift.

The v1 plain-English surface survives through compile_text() on the v2
compiler, which reuses the v1 IntentParser and lifts the result. It is a
compatibility surface, not the product — see docs/RC_V2_PICKED.md for
the deprecation path.
"""
from __future__ import annotations

from typing import Callable

from dreamlayer.reality_compiler.schema import (
    BehaviorIntent, RoundTimerIntent, OvertimeTimerIntent,
    StopwatchIntent, IntervalTimerIntent, SimpleCounterIntent,
    BatteryWarningIntent, TeleprompterIntent, CoachingCueIntent,
    PointsMarkerIntent, NextClassIntent, TextSubtitlesIntent,
    HabitReminderIntent, ReactTimerIntent, GestureRepeaterIntent,
    SpeakerIndicatorIntent,
)

from .figment import (
    Figment, Scene, TextLine, PulseSpec, CounterDecl, CounterOp,
    Guard, Transition, END, SELF,
)

_TRIGGER = {"single_click": "single", "double_click": "double",
            "tap": "single", "long_press": "long", "tilt_down": "imu_tap"}

_WARN_COLOR = {"RED": "accent_error", "YELLOW": "accent_attention"}


def lift(intent: BehaviorIntent) -> Figment:
    """Lift a v1 BehaviorIntent into a semantically equivalent Figment."""
    intent.validate()
    fn = _LIFTERS.get(intent.type)
    if fn is None:
        raise KeyError(f"no v2 lift for v1 behavior {intent.type!r}")
    fig = fn(intent)
    fig.meta["origin"] = "v1_lift"
    fig.meta["v1_type"] = intent.type
    return fig


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _armed(fig: Figment, title: str, hint_event: str, target: str) -> Scene:
    hint = {"single": "tap: start", "double": "double-tap: start",
            "long": "hold: start", "imu_tap": "tilt: show"}[hint_event]
    armed = fig.add_scene(Scene(id="armed", lines=[
        TextLine(title[:24], row=0, size="sm", color="text_secondary"),
        TextLine("READY", row=1, size="lg"),
        TextLine(hint, row=3, size="sm", color="text_secondary"),
    ]))
    armed.on[hint_event] = Transition(target=target)
    return armed


def _countdown_scene(sid: str, label: str, secs: float,
                     pulse: PulseSpec | None = None) -> Scene:
    return Scene(
        id=sid,
        duration_sec=float(secs),
        tick="countdown",
        lines=[TextLine(label[:24], row=0, size="sm", color="text_secondary"),
               TextLine("{remaining}", row=1, size="lg")],
        pulse=pulse,
    )


# ---------------------------------------------------------------------------
# the fifteen lifts
# ---------------------------------------------------------------------------

def _round_timer(i: RoundTimerIntent) -> Figment:
    fig = Figment(name="Round timer", initial="armed")
    trig = _TRIGGER[i.trigger]
    pulse = None
    if i.warning_start_sec > 0:
        pulse = PulseSpec(window_sec=min(i.warning_start_sec, i.duration_sec),
                          color=_WARN_COLOR[i.warning_color], rate_hz=2.0)
    rnd = fig.add_scene(_countdown_scene("round", "ROUND",
                                         i.duration_sec, pulse))
    if i.overtime_sec > 0:
        ot = fig.add_scene(_countdown_scene("overtime", "OT", i.overtime_sec,
                                            PulseSpec(min(5, i.overtime_sec),
                                                      "accent_error", 2.0)))
        rnd.on_timeout = [Transition(target="overtime")]
        ot.on_timeout = [Transition(target="over")]
    else:
        rnd.on_timeout = [Transition(target="over")]
    fig.add_scene(Scene(id="over", duration_sec=3.0,
                               lines=[TextLine("OVER", row=1, size="lg",
                                               color="accent_attention")],
                               on_timeout=[Transition(target="armed")]))
    _armed(fig, "ROUND TIMER", trig, "round")
    # v1 semantics: the trigger also stops a running round
    rnd.on[trig] = Transition(target="armed")
    return fig


def _overtime_timer(i: OvertimeTimerIntent) -> Figment:
    fig = Figment(name="Overtime timer", initial="armed")
    trig = _TRIGGER[i.trigger]
    main = fig.add_scene(_countdown_scene("main", "TIME", i.duration_sec))
    ot = fig.add_scene(Scene(
        id="overtime", duration_sec=float(i.overtime_sec), tick="countup",
        lines=[TextLine("OVERTIME", row=0, size="sm", color="accent_error"),
               TextLine("+{elapsed}", row=1, size="lg", color="accent_error")],
        on_timeout=[Transition(target=END)],
        pulse=PulseSpec(min(10, i.overtime_sec), "accent_error", 2.0),
    ))
    main.on_timeout = [Transition(target="overtime")]
    main.on[trig] = Transition(target="armed")
    ot.on[trig] = Transition(target="armed")
    _armed(fig, "OVERTIME TIMER", trig, "main")
    return fig


def _stopwatch(i: StopwatchIntent) -> Figment:
    fig = Figment(name="Stopwatch", initial="armed")
    start = _TRIGGER[i.trigger_start]
    reset = _TRIGGER[i.trigger_reset]
    run = fig.add_scene(Scene(
        id="running", tick="countup",
        lines=[TextLine("RUNNING", row=0, size="sm", color="accent_memory"),
               TextLine("{elapsed}", row=1, size="lg")],
    ))
    stop = fig.add_scene(Scene(
        id="stopped",
        lines=[TextLine("STOPPED", row=0, size="sm", color="text_secondary"),
               TextLine("{elapsed}", row=1, size="lg")],
    ))
    run.on[start] = Transition(target="stopped")
    stop.on[start] = Transition(target="running")
    for sid in ("running", "stopped"):
        fig.scenes[sid].on[reset] = Transition(target="armed")
    _armed(fig, "STOPWATCH", start, "running")
    return fig


def _interval_timer(i: IntervalTimerIntent) -> Figment:
    fig = Figment(name="Interval timer", initial="armed")
    trig = _TRIGGER[i.trigger]
    fig.add_counter(CounterDecl("round", start=1, lo=1, hi=i.rounds))
    work = fig.add_scene(Scene(
        id="work", duration_sec=float(i.work_sec), tick="countdown",
        lines=[TextLine("WORK {count:round}/%d" % i.rounds, row=0,
                        size="sm", color="accent_attention"),
               TextLine("{remaining}", row=1, size="lg")],
    ))
    if i.rest_sec > 0:
        rest = fig.add_scene(Scene(
            id="rest", duration_sec=float(i.rest_sec), tick="countdown",
            lines=[TextLine("REST", row=0, size="sm", color="accent_memory"),
                   TextLine("{remaining}", row=1, size="lg")],
        ))
        cycle_end = rest
    else:
        cycle_end = work
    cycle_end.on_timeout = [
        Transition(target="done", when=Guard("round", "ge", i.rounds)),
        Transition(target="work", counter_ops=[CounterOp("round", "inc", 1)]),
    ]
    if i.rest_sec > 0:
        work.on_timeout = [Transition(target="rest")]
    fig.add_scene(Scene(id="done", duration_sec=4.0,
                        lines=[TextLine("DONE!", row=1, size="lg",
                                        color="accent_success")],
                        on_timeout=[Transition(target="armed")]))
    work.on[trig] = Transition(target="armed")   # v1: trigger stops
    _armed(fig, "INTERVALS", trig, "work")
    # entering work from armed resets the round counter
    fig.scenes["armed"].on[trig] = Transition(
        target="work", counter_ops=[CounterOp("round", "set", 1)])
    return fig


def _simple_counter(i: SimpleCounterIntent) -> Figment:
    fig = Figment(name="Counter", initial="count")
    fig.add_counter(CounterDecl("tally", start=i.start_value))
    scene = fig.add_scene(Scene(
        id="count",
        lines=[TextLine("COUNT", row=0, size="sm", color="text_secondary"),
               TextLine("{count:tally}", row=1, size="lg")],
    ))
    scene.on[_TRIGGER[i.trigger]] = Transition(
        target=SELF, counter_ops=[CounterOp("tally", "inc", i.increment)])
    scene.on[_TRIGGER[i.reset_trigger]] = Transition(
        target=SELF, counter_ops=[CounterOp("tally", "set", i.start_value)])
    return fig


def _battery_warning(i: BatteryWarningIntent) -> Figment:
    fig = Figment(name="Battery warning", initial="watch",
                  battery_below=i.threshold_pct)
    watch = fig.add_scene(Scene(id="watch", lines=[]))
    watch.on["battery_low"] = Transition(target="warn")
    fig.add_scene(Scene(
        id="warn", duration_sec=3.0,
        lines=[TextLine("LOW BATTERY", row=0, size="md",
                        color=_WARN_COLOR[i.warning_color]),
               TextLine("charge soon", row=2, size="sm",
                        color="text_secondary")],
        on_timeout=[Transition(target="watch")],
    ))
    return fig


def _teleprompter(i: TeleprompterIntent) -> Figment:
    # v1's template paged host-sent lines; the stage displays the host-fed
    # text slot, advanced by "text" pushes at the host's scroll cadence.
    fig = Figment(name="Teleprompter", initial="page")
    page = fig.add_scene(Scene(
        id="page",
        lines=[TextLine("{slot}", row=1, size="md"),
               TextLine("teleprompter", row=4, size="sm",
                        color="text_secondary")],
    ))
    page.on["text"] = Transition(target=SELF)
    page.on["long"] = Transition(target=END)
    fig.meta["scroll_speed"] = i.scroll_speed
    fig.meta["tilt_control"] = i.tilt_control
    return fig


def _coaching_cue(i: CoachingCueIntent) -> Figment:
    fig = Figment(name="Coach cue", initial="ready")
    ready = fig.add_scene(Scene(
        id="ready",
        lines=[TextLine("COACH CUE READY", row=1, size="sm",
                        color="text_secondary")],
    ))
    show_sec = max(0.5, i.display_duration_ms / 1000.0)
    for code, label in sorted(i.cue_map.items()):
        sid = f"cue_{code}"
        fig.add_scene(Scene(
            id=sid, duration_sec=show_sec,
            lines=[TextLine(str(label)[:24], row=1, size="lg",
                            color="accent_attention")],
            on_timeout=[Transition(target="ready")],
        ))
        ready.on[f"ble:{code}"] = Transition(target=sid)
    return fig


def _points_marker(i: PointsMarkerIntent) -> Figment:
    fig = Figment(name="Points", initial="points")
    fig.add_counter(CounterDecl("points", start=0))
    scene = fig.add_scene(Scene(
        id="points",
        lines=[TextLine("POINTS", row=0, size="sm", color="text_secondary"),
               TextLine("{count:points}", row=1, size="lg")],
    ))
    scene.on[_TRIGGER[i.trigger]] = Transition(
        target=SELF, counter_ops=[CounterOp("points", "inc", 1)],
        emit="point" if i.send_to_host else None)
    scene.on[_TRIGGER[i.undo_trigger]] = Transition(
        target=SELF, counter_ops=[CounterOp("points", "dec", 1)])
    return fig


def _next_class(i: NextClassIntent) -> Figment:
    fig = Figment(name="Next class", initial="idle")
    idle = fig.add_scene(Scene(id="idle", lines=[]))
    idle.on[_TRIGGER[i.trigger]] = Transition(target="show")
    fig.add_scene(Scene(
        id="show", duration_sec=float(i.display_duration_sec),
        lines=[TextLine("NEXT CLASS", row=0, size="sm",
                        color="text_secondary"),
               TextLine("{slot}", row=1, size="md")],
        on_timeout=[Transition(target="idle")],
    ))
    return fig


def _text_subtitles(i: TextSubtitlesIntent) -> Figment:
    fig = Figment(name="Subtitles", initial="subs")
    subs = fig.add_scene(Scene(
        id="subs",
        lines=[TextLine("{slot}", row=2, size=i.font_size)],
    ))
    subs.on["text"] = Transition(target=SELF)
    subs.on["long"] = Transition(target=END)
    fig.meta["position_y"] = i.position_y
    fig.meta["fade_ms"] = i.fade_ms
    return fig


def _habit_reminder(i: HabitReminderIntent) -> Figment:
    fig = Figment(name="Habit reminder", initial="wait")
    fig.add_scene(Scene(
        id="wait", duration_sec=float(i.interval_min * 60),
        lines=[],
        on_timeout=[Transition(target="remind")],
    ))
    fig.add_scene(Scene(
        id="remind", duration_sec=float(i.display_duration_sec),
        lines=[TextLine(i.reminder_text[:24], row=1, size="md",
                        color="accent_memory")],
        on_timeout=[Transition(target="wait")],
    ))
    return fig


def _react_timer(i: ReactTimerIntent) -> Figment:
    fig = Figment(name="Reaction timer", initial="armed")
    trig = _TRIGGER[i.trigger]
    fig.add_scene(Scene(
        id="ready", duration_range=(max(0.5, i.min_delay_ms / 1000.0),
                                    max(0.6, i.max_delay_ms / 1000.0)),
        lines=[TextLine("Get ready...", row=1, size="md",
                        color="text_secondary")],
        on_timeout=[Transition(target="go")],
    ))
    go = fig.add_scene(Scene(
        id="go", tick="countup",
        lines=[TextLine("GO!", row=1, size="lg", color="accent_success")],
    ))
    go.on[trig] = Transition(target="result")
    fig.add_scene(Scene(
        id="result", duration_sec=2.0,
        lines=[TextLine("{elapsed_ms} ms", row=1, size="lg")],
        on_timeout=[Transition(target="ready")],
    ))
    _armed(fig, "REACTION", trig, "ready")
    return fig


def _gesture_repeater(i: GestureRepeaterIntent) -> Figment:
    fig = Figment(name="Gesture repeater", initial="listen")
    listen = fig.add_scene(Scene(
        id="listen",
        lines=[TextLine("gesture → host", row=1, size="sm",
                        color="text_secondary")],
    ))
    listen.on[_TRIGGER[i.trigger]] = Transition(
        target=SELF, emit=i.event_name[:16])
    return fig


def _speaker_indicator(i: SpeakerIndicatorIntent) -> Figment:
    fig = Figment(name="Speaker", initial="quiet")
    quiet = fig.add_scene(Scene(id="quiet", lines=[]))
    quiet.on["text"] = Transition(target="speaking")
    show = Scene(
        id="speaking", duration_sec=max(0.5, i.display_duration_ms / 1000.0),
        lines=[TextLine("{slot}" if i.show_name else "speaking", row=1,
                        size="md", color="accent_memory")],
        on_timeout=[Transition(target="quiet")],
    )
    show.on["text"] = Transition(target=SELF)
    fig.add_scene(show)
    return fig


_LIFTERS: dict[str, Callable[..., Figment]] = {
    "round_timer": _round_timer,
    "overtime_timer": _overtime_timer,
    "stopwatch": _stopwatch,
    "interval_timer": _interval_timer,
    "simple_counter": _simple_counter,
    "battery_warning": _battery_warning,
    "teleprompter": _teleprompter,
    "coaching_cue": _coaching_cue,
    "points_marker": _points_marker,
    "next_class": _next_class,
    "text_subtitles": _text_subtitles,
    "habit_reminder": _habit_reminder,
    "react_timer": _react_timer,
    "gesture_repeater": _gesture_repeater,
    "speaker_indicator": _speaker_indicator,
}

ALL_V1_TYPES = sorted(_LIFTERS)
