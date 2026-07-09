"""EyeMU-style gaze+IMU micro-gestures — nod = confirm, double-tap = repeat,
anchored to what the user was looking at.

ADD-alongside: new sibling to imu_reactor.py (untouched). No hard dep — EyeMU is
a technique, not a pip package — so this is a self-contained detector with a
clean threshold heuristic; a learned model can replace `detect()` later.
"""
from __future__ import annotations
import time


class EyeMUGestures:
    available = True  # pure-Python heuristic, always available

    def __init__(self, nod_thresh: float = 0.35, tap_window_s: float = 0.4):
        self.nod_thresh = nod_thresh
        self.tap_window_s = tap_window_s
        self._last_tap = 0.0

    def detect(self, imu: dict, now: float | None = None) -> str | None:
        """`imu` = {pitch, roll, yaw, tap?}. Returns 'confirm' (nod), 'repeat'
        (double-tap), or None."""
        now = time.monotonic() if now is None else now
        if imu.get("tap"):
            if now - self._last_tap <= self.tap_window_s:
                self._last_tap = 0.0
                return "repeat"
            self._last_tap = now
        pitch = abs(float(imu.get("pitch", 0.0)))
        if pitch >= self.nod_thresh:
            return "confirm"
        return None
