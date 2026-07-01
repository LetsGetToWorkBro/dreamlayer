"""dream_mode/imu_reactor.py — Motion → geometry distortion BLE frame."""
from __future__ import annotations
from typing import Optional
import math

TILT_THRESHOLD = 0.08
SPIN_THRESHOLD = 0.15


class ImuReactor:
    """Converts IMU motion deltas into geometry distortion BLE commands."""

    def __init__(self):
        self._smoothed_tilt: float = 0.0
        self._smoothed_spin: float = 0.0

    def tick(self, ctx) -> Optional[dict]:
        if not ctx.imu_delta:
            return None
        delta = ctx.imu_delta
        tilt = math.sqrt(
            delta.get("dx", 0.0) ** 2 + delta.get("dy", 0.0) ** 2
        )
        spin = abs(delta.get("dz", 0.0))
        self._smoothed_tilt = 0.7 * self._smoothed_tilt + 0.3 * tilt
        self._smoothed_spin = 0.7 * self._smoothed_spin + 0.3 * spin
        if self._smoothed_tilt < TILT_THRESHOLD and self._smoothed_spin < SPIN_THRESHOLD:
            return None
        warp_x = round(min(self._smoothed_tilt * 8.0, 1.0), 3)
        warp_z = round(min(self._smoothed_spin * 5.0, 1.0), 3)
        return {
            "cmd": "geometry_warp",
            "warp_x": warp_x,
            "warp_z": warp_z,
            "duration_ms": 500,
        }
