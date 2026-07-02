"""reality_compiler/intent_parser.py — Natural language → structured BehaviorIntent.

MVP: deterministic pattern-matching, no LLM dependency.
v2 upgrade path: swap _llm_parse() stub in for full LLM JSON mode.

Supported behaviors (15)
------------------------
  round_timer, overtime_timer, stopwatch, interval_timer, simple_counter,
  battery_warning, teleprompter, coaching_cue, points_marker, next_class,
  text_subtitles, habit_reminder, react_timer, gesture_repeater,
  speaker_indicator
"""
from __future__ import annotations

import re
from typing import Optional

from .schema import (
    BehaviorIntent, RoundTimerIntent, OvertimeTimerIntent,
    StopwatchIntent, IntervalTimerIntent, SimpleCounterIntent,
    BatteryWarningIntent, TeleprompterIntent, CoachingCueIntent,
    PointsMarkerIntent, NextClassIntent, TextSubtitlesIntent,
    HabitReminderIntent, ReactTimerIntent, GestureRepeaterIntent,
    SpeakerIndicatorIntent, ValidationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORD_TO_SEC: dict[str, int] = {
    "one": 60, "two": 120, "three": 180, "four": 240, "five": 300,
    "six": 360, "seven": 420, "eight": 480, "nine": 540, "ten": 600,
}


def _parse_duration(text: str) -> Optional[int]:
    """Return seconds from phrases like '3 minute', '90 second', 'five min'."""
    text = text.lower()
    # numeric minutes
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:minute|min)', text)
    if m:
        return int(float(m.group(1)) * 60)
    # numeric seconds
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:second|sec)', text)
    if m:
        return int(float(m.group(1)))
    # word minutes
    for word, secs in _WORD_TO_SEC.items():
        if re.search(rf'\b{word}\s*(?:minute|min)', text):
            return secs
    return None


def _parse_int(text: str, pattern: str) -> Optional[int]:
    """Extract first integer matching a regex group."""
    m = re.search(pattern, text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _contains(text: str, *keywords: str) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def _trigger(text: str, default: str = "double_click") -> str:
    t = text.lower()
    if "single" in t or "one tap" in t or "one click" in t:
        return "single_click"
    if "double" in t or "two tap" in t or "two click" in t:
        return "double_click"
    if "tap" in t:
        return "tap"
    return default


# ---------------------------------------------------------------------------
# IntentParser
# ---------------------------------------------------------------------------

class IntentParser:
    """Converts natural language strings into BehaviorIntent dataclasses.

    Usage
    -----
        parser = IntentParser()
        intent = parser.parse("3 minute round timer with 20 seconds overtime")
        # → RoundTimerIntent(duration_sec=180, overtime_sec=20, ...)

    Raises
    ------
    ValueError  — if the input cannot be mapped to any known behavior.
    """

    def parse(self, text: str) -> BehaviorIntent:
        """Parse *text* and return the best-matching BehaviorIntent."""
        t = text.lower().strip()

        # Priority order matters — more specific before more general
        for fn in [
            self._try_interval_timer,
            self._try_overtime_timer,
            self._try_react_timer,
            self._try_round_timer,
            self._try_stopwatch,
            self._try_simple_counter,
            self._try_battery_warning,
            self._try_teleprompter,
            self._try_coaching_cue,
            self._try_points_marker,
            self._try_next_class,
            self._try_text_subtitles,
            self._try_habit_reminder,
            self._try_gesture_repeater,
            self._try_speaker_indicator,
        ]:
            result = fn(t)
            if result is not None:
                result.validate()
                return result

        raise ValueError(
            f"Cannot parse intent from: {text!r}\n"
            "Supported: round_timer, interval_timer, stopwatch, counter, "
            "battery_warning, teleprompter, coaching_cue, points_marker, "
            "next_class, text_subtitles, habit_reminder, react_timer, "
            "gesture_repeater, speaker_indicator"
        )

    def describe(self, intent: BehaviorIntent) -> str:
        """Return a human-readable summary of a parsed intent."""
        lines = [f"Behavior: {intent.type}"]
        for k, v in intent.__dict__.items():
            if k != "type":
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Individual matchers
    # ------------------------------------------------------------------

    def _try_round_timer(self, t: str) -> Optional[RoundTimerIntent]:
        if not _contains(t, "round", "timer", "countdown"):
            return None
        duration = _parse_duration(t) or 180
        # overtime: look for 'overtime' or 'extra' keywords
        ot = None
        if _contains(t, "overtime", "extra time", "extra"):
            ot = _parse_int(t, r'(\d+)\s*(?:second|sec)s?\s+(?:overtime|extra)')
            if ot is None:
                ot = _parse_int(t, r'(?:overtime|extra)\s+(?:of\s+)?(\d+)')
            if ot is None:
                ot = 30  # sensible default
        warning = _parse_int(t, r'warn(?:ing)?\s+(?:at\s+)?(\d+)') or 10
        color = "RED" if _contains(t, "red") else "YELLOW" if _contains(t, "yellow") else "RED"
        return RoundTimerIntent(
            duration_sec=duration,
            overtime_sec=ot if ot is not None else 0,
            warning_start_sec=min(warning, duration),
            warning_color=color,
            trigger=_trigger(t, "double_click"),
        )

    def _try_overtime_timer(self, t: str) -> Optional[OvertimeTimerIntent]:
        if not (_contains(t, "overtime") and not _contains(t, "round")):
            return None
        duration = _parse_duration(t) or 300
        ot = _parse_int(t, r'overtime\s+(?:of\s+)?(\d+)') or 60
        return OvertimeTimerIntent(
            duration_sec=duration,
            overtime_sec=ot,
            trigger=_trigger(t, "double_click"),
        )

    def _try_stopwatch(self, t: str) -> Optional[StopwatchIntent]:
        if not _contains(t, "stopwatch", "elapsed", "lap timer"):
            return None
        return StopwatchIntent(
            trigger_start=_trigger(t, "single_click"),
        )

    def _try_interval_timer(self, t: str) -> Optional[IntervalTimerIntent]:
        if not _contains(t, "interval", "work", "rest", "hiit", "tabata"):
            return None
        # need at least one timer word to avoid false-positives
        if not _contains(t, "interval", "hiit", "tabata", "work", "rest"):
            return None
        # parse work/rest
        work = _parse_int(t, r'(\d+)\s*(?:sec|second)s?\s+work') \
               or _parse_int(t, r'work\s+(?:for\s+)?(\d+)') \
               or 45
        rest = _parse_int(t, r'(\d+)\s*(?:sec|second)s?\s+rest') \
               or _parse_int(t, r'rest\s+(?:for\s+)?(\d+)') \
               or 15
        rounds = _parse_int(t, r'(\d+)\s+round') \
                 or _parse_int(t, r'(\d+)\s+rep') \
                 or 8
        return IntervalTimerIntent(
            work_sec=work, rest_sec=rest, rounds=rounds,
            trigger=_trigger(t, "double_click"),
        )

    def _try_simple_counter(self, t: str) -> Optional[SimpleCounterIntent]:
        if not _contains(t, "counter", "count", "tally", "score"):
            return None
        start = _parse_int(t, r'start(?:ing)?\s+(?:at\s+|from\s+)?(\d+)') or 0
        inc = _parse_int(t, r'(?:by|increment)\s+(\d+)') or 1
        return SimpleCounterIntent(
            start_value=start,
            increment=inc,
            trigger=_trigger(t, "single_click"),
        )

    def _try_battery_warning(self, t: str) -> Optional[BatteryWarningIntent]:
        if not _contains(t, "battery", "charge", "power level"):
            return None
        threshold = _parse_int(t, r'(\d+)\s*(?:percent|%)') or 20
        color = "YELLOW" if _contains(t, "yellow") else "RED"
        return BatteryWarningIntent(
            threshold_pct=threshold,
            warning_color=color,
        )

    def _try_teleprompter(self, t: str) -> Optional[TeleprompterIntent]:
        if not _contains(t, "teleprompter", "prompter", "scroll text", "autocue"):
            return None
        tilt = not _contains(t, "no tilt", "fixed speed")
        return TeleprompterIntent(tilt_control=tilt)

    def _try_coaching_cue(self, t: str) -> Optional[CoachingCueIntent]:
        if not _contains(t, "coaching", "coach cue", "coach signal", "cue receiver", "coaching cue"):
            return None
        return CoachingCueIntent()

    def _try_points_marker(self, t: str) -> Optional[PointsMarkerIntent]:
        if not _contains(t, "point", "mark", "score", "log event"):
            return None
        # don't match 'counter' or 'tally' — those go to simple_counter
        if _contains(t, "counter", "tally"):
            return None
        return PointsMarkerIntent(
            trigger=_trigger(t, "single_click"),
            send_to_host=not _contains(t, "local only", "no send"),
        )

    def _try_next_class(self, t: str) -> Optional[NextClassIntent]:
        if not _contains(t, "next class", "schedule", "class time"):
            return None
        return NextClassIntent()

    def _try_text_subtitles(self, t: str) -> Optional[TextSubtitlesIntent]:
        if not _contains(t, "subtitle", "caption", "transcription overlay"):
            return None
        return TextSubtitlesIntent()

    def _try_habit_reminder(self, t: str) -> Optional[HabitReminderIntent]:
        if not _contains(t, "reminder", "remind", "habit", "nudge"):
            return None
        interval = _parse_int(t, r'every\s+(\d+)\s*(?:minute|min)') or 30
        text_m = re.search(r'remind(?:er)?\s+(?:me\s+)?(?:to\s+)?["\']?([^"\',.]+)', t)
        reminder_text = text_m.group(1).strip().capitalize() if text_m else "Reminder"
        return HabitReminderIntent(
            reminder_text=reminder_text,
            interval_min=interval,
        )

    def _try_react_timer(self, t: str) -> Optional[ReactTimerIntent]:
        if not _contains(t, "reaction", "react", "reflex", "random flash"):
            return None
        min_ms = _parse_int(t, r'(\d+)\s*ms\s+min') or 1000
        max_ms = _parse_int(t, r'(\d+)\s*ms\s+max') or 4000
        return ReactTimerIntent(min_delay_ms=min_ms, max_delay_ms=max_ms)

    def _try_gesture_repeater(self, t: str) -> Optional[GestureRepeaterIntent]:
        if not _contains(t, "gesture", "tap event", "send tap", "broadcast tap"):
            return None
        return GestureRepeaterIntent(trigger=_trigger(t, "tap"))

    def _try_speaker_indicator(self, t: str) -> Optional[SpeakerIndicatorIntent]:
        if not _contains(t, "speaker", "who is talking", "who is speaking", "talking indicator"):
            return None
        return SpeakerIndicatorIntent()
