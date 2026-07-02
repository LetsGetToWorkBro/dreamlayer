"""reality_compiler/codegen.py — Lua + host-glue Python codegen.

Takes a BehaviorIntent + matching BehaviorTemplate and produces:
  - lua_code  : str  — ready to write to main.lua
  - host_code : str  — ready to write to deploy.py

Uses Python's built-in string.Template (${variable}) — no Jinja dependency.
"""
from __future__ import annotations

from string import Template
from typing import Any

from .schema import (
    BehaviorIntent, RoundTimerIntent, OvertimeTimerIntent,
    StopwatchIntent, IntervalTimerIntent, SimpleCounterIntent,
    BatteryWarningIntent, TeleprompterIntent, CoachingCueIntent,
    PointsMarkerIntent, HabitReminderIntent, ReactTimerIntent,
    GestureRepeaterIntent, ValidationError,
)
from .template_library import get as get_template


class CodeGenerator:
    """Converts a BehaviorIntent into deployable Lua + Python host code."""

    def generate(self, intent: BehaviorIntent) -> tuple[str, str]:
        """Return (lua_code, host_code) for *intent*.

        Raises KeyError if no template exists for intent.type.
        Raises ValidationError if the intent is internally inconsistent.
        """
        intent.validate()
        tmpl = get_template(intent.type)
        vars_ = self._intent_to_vars(intent)
        lua_code  = Template(tmpl.lua_template).safe_substitute(vars_)
        host_code = Template(tmpl.host_template).safe_substitute(vars_)
        return lua_code, host_code

    # ------------------------------------------------------------------
    # Intent → substitution variable dict
    # ------------------------------------------------------------------

    def _intent_to_vars(self, intent: BehaviorIntent) -> dict[str, Any]:
        """Flatten intent fields + add derived vars needed by templates."""
        # Start with all dataclass fields
        vars_: dict[str, Any] = {
            k: v for k, v in intent.__dict__.items()
        }
        # Always-present host vars
        vars_.setdefault("host_extra", "# no extra host logic")
        vars_.setdefault("run_sec", 3600)  # run for 1 hour by default

        # Behavior-specific derived vars
        if isinstance(intent, PointsMarkerIntent):
            if intent.send_to_host:
                vars_["send_expr"] = 'frame.bluetooth.send(tostring(points))'
            else:
                vars_["send_expr"] = "-- local only"
            vars_["undo_trigger"] = "long_press"

        if isinstance(intent, TeleprompterIntent):
            vars_["tilt_control"] = "true" if intent.tilt_control else "false"

        if isinstance(intent, StopwatchIntent):
            vars_.setdefault("trigger_start", "single_click")
            vars_.setdefault("trigger_reset", "long_press")

        # Ensure all values are Lua/Python-safe strings
        for k, v in vars_.items():
            if isinstance(v, bool):
                vars_[k] = "true" if v else "false"

        return vars_
