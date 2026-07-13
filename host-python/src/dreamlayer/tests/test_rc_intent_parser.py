"""Tests for reality_compiler.IntentParser (18 tests)."""
import pytest
from dreamlayer.reality_compiler.intent_parser import IntentParser
from dreamlayer.reality_compiler.schema import (
    RoundTimerIntent, StopwatchIntent,
    IntervalTimerIntent, SimpleCounterIntent, BatteryWarningIntent,
    TeleprompterIntent, CoachingCueIntent, HabitReminderIntent, ReactTimerIntent,
)


@pytest.fixture
def parser():
    return IntentParser()


# ------------------------------------------------------------------
# Round timer
# ------------------------------------------------------------------

def test_parse_round_timer_basic(parser):
    intent = parser.parse("3 minute round timer")
    assert isinstance(intent, RoundTimerIntent)
    assert intent.duration_sec == 180


def test_parse_round_timer_with_overtime(parser):
    intent = parser.parse("3 minute round timer with 20 seconds overtime")
    assert isinstance(intent, RoundTimerIntent)
    assert intent.duration_sec == 180
    assert intent.overtime_sec == 20


def test_parse_round_timer_5min(parser):
    intent = parser.parse("5 min round timer")
    assert isinstance(intent, RoundTimerIntent)
    assert intent.duration_sec == 300


def test_parse_round_timer_word(parser):
    intent = parser.parse("five minute round timer")
    assert isinstance(intent, RoundTimerIntent)
    assert intent.duration_sec == 300


def test_parse_round_timer_warning_color(parser):
    intent = parser.parse("3 minute round timer yellow warning")
    assert isinstance(intent, RoundTimerIntent)
    assert intent.warning_color == "YELLOW"


# ------------------------------------------------------------------
# Interval timer
# ------------------------------------------------------------------

def test_parse_interval_timer(parser):
    intent = parser.parse("45 seconds work 15 seconds rest 8 rounds interval timer")
    assert isinstance(intent, IntervalTimerIntent)
    assert intent.work_sec == 45
    assert intent.rest_sec == 15
    assert intent.rounds == 8


def test_parse_tabata(parser):
    intent = parser.parse("tabata 20 seconds work 10 seconds rest")
    assert isinstance(intent, IntervalTimerIntent)
    assert intent.work_sec == 20
    assert intent.rest_sec == 10


# ------------------------------------------------------------------
# Stopwatch
# ------------------------------------------------------------------

def test_parse_stopwatch(parser):
    intent = parser.parse("stopwatch")
    assert isinstance(intent, StopwatchIntent)


def test_parse_elapsed_timer(parser):
    intent = parser.parse("elapsed time tracker")
    assert isinstance(intent, StopwatchIntent)


# ------------------------------------------------------------------
# Counter
# ------------------------------------------------------------------

def test_parse_counter(parser):
    intent = parser.parse("simple counter starting at 0")
    assert isinstance(intent, SimpleCounterIntent)
    assert intent.start_value == 0


def test_parse_counter_increment(parser):
    intent = parser.parse("counter increment by 2")
    assert isinstance(intent, SimpleCounterIntent)
    assert intent.increment == 2


# ------------------------------------------------------------------
# Battery warning
# ------------------------------------------------------------------

def test_parse_battery_warning(parser):
    intent = parser.parse("flash a warning when battery drops below 15%")
    assert isinstance(intent, BatteryWarningIntent)
    assert intent.threshold_pct == 15


def test_parse_battery_default_threshold(parser):
    intent = parser.parse("battery warning")
    assert isinstance(intent, BatteryWarningIntent)
    assert intent.threshold_pct == 20


# ------------------------------------------------------------------
# Teleprompter
# ------------------------------------------------------------------

def test_parse_teleprompter(parser):
    intent = parser.parse("teleprompter that scrolls faster when I tilt forward")
    assert isinstance(intent, TeleprompterIntent)
    assert intent.tilt_control is True


# ------------------------------------------------------------------
# Coaching cue
# ------------------------------------------------------------------

def test_parse_coaching_cue(parser):
    intent = parser.parse("coaching cue receiver for BJJ")
    assert isinstance(intent, CoachingCueIntent)


# ------------------------------------------------------------------
# Habit reminder
# ------------------------------------------------------------------

def test_parse_habit_reminder(parser):
    intent = parser.parse("remind me every 30 minutes")
    assert isinstance(intent, HabitReminderIntent)
    assert intent.interval_min == 30


# ------------------------------------------------------------------
# React timer
# ------------------------------------------------------------------

def test_parse_react_timer(parser):
    intent = parser.parse("reaction timer with random flash")
    assert isinstance(intent, ReactTimerIntent)


# ------------------------------------------------------------------
# Unknown input
# ------------------------------------------------------------------

def test_parse_unknown_raises(parser):
    with pytest.raises(ValueError, match="Cannot parse intent"):
        parser.parse("make me a sandwich")
