"""reality_compiler/schema.py — Typed intent dataclasses for every behavior.

Every intent produced by IntentParser is one of these dataclasses.
Codegen reads the fields directly — no dict access, no key errors.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional


class ValidationError(ValueError):
    """Raised when an intent field is out of range or logically invalid."""


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass
class BehaviorIntent:
    """Abstract base — all concrete intents inherit from this."""
    type: str = field(init=False)

    def validate(self) -> None:  # pragma: no cover
        """Subclasses may raise ValidationError."""


# ---------------------------------------------------------------------------
# Timer family
# ---------------------------------------------------------------------------

@dataclass
class RoundTimerIntent(BehaviorIntent):
    duration_sec: int = 180
    overtime_sec: int = 30
    warning_start_sec: int = 10
    warning_color: Literal["RED", "YELLOW"] = "RED"
    trigger: Literal["double_click", "single_click", "tap"] = "double_click"

    def __post_init__(self) -> None:
        self.type = "round_timer"

    def validate(self) -> None:
        if self.duration_sec < 10:
            raise ValidationError("duration_sec must be >= 10")
        if self.overtime_sec < 0:
            raise ValidationError("overtime_sec must be >= 0")
        if self.warning_start_sec < 0 or self.warning_start_sec > self.duration_sec:
            raise ValidationError("warning_start_sec must be in [0, duration_sec]")


@dataclass
class OvertimeTimerIntent(BehaviorIntent):
    duration_sec: int = 300
    overtime_sec: int = 60
    trigger: Literal["double_click", "single_click"] = "double_click"

    def __post_init__(self) -> None:
        self.type = "overtime_timer"

    def validate(self) -> None:
        if self.duration_sec < 10:
            raise ValidationError("duration_sec must be >= 10")


@dataclass
class StopwatchIntent(BehaviorIntent):
    trigger_start: Literal["single_click", "double_click"] = "single_click"
    trigger_reset: Literal["long_press", "double_click"] = "long_press"

    def __post_init__(self) -> None:
        self.type = "stopwatch"


@dataclass
class IntervalTimerIntent(BehaviorIntent):
    work_sec: int = 45
    rest_sec: int = 15
    rounds: int = 8
    trigger: Literal["double_click", "single_click"] = "double_click"

    def __post_init__(self) -> None:
        self.type = "interval_timer"

    def validate(self) -> None:
        if self.work_sec < 5:
            raise ValidationError("work_sec must be >= 5")
        if self.rest_sec < 0:
            raise ValidationError("rest_sec must be >= 0")
        if self.rounds < 1:
            raise ValidationError("rounds must be >= 1")


@dataclass
class SimpleCounterIntent(BehaviorIntent):
    start_value: int = 0
    increment: int = 1
    trigger: Literal["single_click", "double_click"] = "single_click"
    reset_trigger: Literal["long_press", "double_click"] = "long_press"

    def __post_init__(self) -> None:
        self.type = "simple_counter"


# ---------------------------------------------------------------------------
# Display / utility family
# ---------------------------------------------------------------------------

@dataclass
class BatteryWarningIntent(BehaviorIntent):
    threshold_pct: int = 20
    check_interval_sec: int = 60
    warning_color: Literal["RED", "YELLOW"] = "RED"

    def __post_init__(self) -> None:
        self.type = "battery_warning"

    def validate(self) -> None:
        if not 1 <= self.threshold_pct <= 99:
            raise ValidationError("threshold_pct must be in [1, 99]")


@dataclass
class TeleprompterIntent(BehaviorIntent):
    text: str = "Your text here"
    scroll_speed: float = 1.0  # lines per second baseline
    tilt_control: bool = True  # head tilt adjusts speed

    def __post_init__(self) -> None:
        self.type = "teleprompter"


@dataclass
class CoachingCueIntent(BehaviorIntent):
    """Receives 1-byte cue codes via BLE from coach dashboard."""
    cue_map: dict = field(default_factory=lambda: {
        1: "ATTACK", 2: "DEFEND", 3: "RESET", 4: "TIME"
    })
    display_duration_ms: int = 3000

    def __post_init__(self) -> None:
        self.type = "coaching_cue"


@dataclass
class PointsMarkerIntent(BehaviorIntent):
    trigger: Literal["single_click", "double_click"] = "single_click"
    undo_trigger: Literal["long_press"] = "long_press"
    send_to_host: bool = True

    def __post_init__(self) -> None:
        self.type = "points_marker"


@dataclass
class NextClassIntent(BehaviorIntent):
    display_duration_sec: int = 8
    trigger: Literal["double_click", "tilt_down"] = "tilt_down"

    def __post_init__(self) -> None:
        self.type = "next_class"


@dataclass
class TextSubtitlesIntent(BehaviorIntent):
    font_size: Literal["sm", "md", "lg"] = "md"
    position_y: int = 200  # pixel row, 0=top
    fade_ms: int = 500

    def __post_init__(self) -> None:
        self.type = "text_subtitles"


@dataclass
class HabitReminderIntent(BehaviorIntent):
    reminder_text: str = "Reminder"
    interval_min: int = 30
    display_duration_sec: int = 5

    def __post_init__(self) -> None:
        self.type = "habit_reminder"

    def validate(self) -> None:
        if self.interval_min < 1:
            raise ValidationError("interval_min must be >= 1")


@dataclass
class ReactTimerIntent(BehaviorIntent):
    min_delay_ms: int = 1000
    max_delay_ms: int = 4000
    trigger: Literal["single_click"] = "single_click"

    def __post_init__(self) -> None:
        self.type = "react_timer"

    def validate(self) -> None:
        if self.min_delay_ms >= self.max_delay_ms:
            raise ValidationError("min_delay_ms must be < max_delay_ms")


@dataclass
class GestureRepeaterIntent(BehaviorIntent):
    trigger: Literal["tap", "single_click", "double_click"] = "tap"
    event_name: str = "gesture"

    def __post_init__(self) -> None:
        self.type = "gesture_repeater"


@dataclass
class SpeakerIndicatorIntent(BehaviorIntent):
    display_duration_ms: int = 2000
    show_name: bool = True

    def __post_init__(self) -> None:
        self.type = "speaker_indicator"
