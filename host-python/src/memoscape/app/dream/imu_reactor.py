"""dream/imu_reactor.py — IMU angular velocity → Line Field 2.0 frames.

Halo Cinema v1 rewrite (docs/HALO_CINEMA_V1.md Phase 3 addendum).

Replaces the 8-vector radial line field with a **12-vector curl-noise
field** derived from IMU yaw + pitch:

  - 12 anchor points sit on a ring around display centre.
  - Each anchor samples a scalar value-noise field; the vector points along
    the field's *curl* (perpendicular to the gradient), so neighbouring
    vectors swirl coherently instead of radiating.
  - The whole field rotates with the **damped** yaw rate and tilts with the
    damped pitch rate.

Gyroscopic damping: raw angular rates pass through a critically-damped
first-order filter (a head *shake* sheds ~90% of its rate within one 2 Hz
tick), so deliberate slow drift steers the field but jitter never does —
kill list #6/#7.

Wire format (one BLE MTU frame, ≤ 240 bytes):
  {"t": "line_field", "v": [x1,y1,x2,y2, ... 12 vectors = 48 ints]}
JSON with 48 three-digit ints ≈ 215 bytes worst case; _WIRE_BUDGET is
asserted in tests.

Legacy {"t": "geometry"} scatter/rotate frames are still emitted for the
fallback renderer path (old firmware), but the Lua side prefers line_field
frames as soon as one arrives.
"""
from __future__ import annotations

import json
import math
import time
from typing import Optional

from ..recall_context import RecallContext

_SLOW_THRESHOLD   = 5.0    # deg/s
_FAST_THRESHOLD   = 20.0   # deg/s
_SCATTER_COOLDOWN = 1.5    # seconds between scatter bursts

# Line Field 2.0
_N_VECTORS   = 12
_RING_R      = 78.0        # anchor ring radius (px)
_LEN_MIN     = 14.0        # vector half-length range (px)
_LEN_MAX     = 34.0
_CX, _CY     = 128, 128
_FIELD_R_MAX = 122         # vectors must stay inside the circular display
_DAMPING     = 0.10        # damped_rate += (raw - damped) * _DAMPING per tick
                           # → ~90% of a transient rate is shed in one tick
_WIRE_BUDGET = 240         # BLE MTU payload budget, bytes


def _vnoise(x: float) -> float:
    """Deterministic 1D value noise in [-1, 1] (same lattice trick as
    lib/easing.lua perlin1d, so device previews match host previews)."""
    def h(n: int) -> float:
        n = int(math.floor(n)) % 289
        return ((n * 34 + 1) * n % 289) / 144.5 - 1.0
    x0 = math.floor(x)
    f = x - x0
    u = f * f * (3 - 2 * f)
    return h(x0) + (h(x0 + 1) - h(x0)) * u


class ImuReactor:
    """Converts IMU delta pose into Line Field 2.0 + geometry BLE commands."""

    def __init__(self) -> None:
        self._last_scatter_t: float = 0.0
        self._yaw_damped:   float = 0.0
        self._pitch_damped: float = 0.0
        self._phase:        float = 0.0   # field rotation accumulator (rad)

    # ------------------------------------------------------------------
    # Line Field 2.0
    # ------------------------------------------------------------------

    def line_field(self, ctx: RecallContext) -> Optional[dict]:
        """Compute the 12-vector curl-noise field frame, or None w/o IMU."""
        if not ctx.has_imu():
            return None

        delta = ctx.imu_delta or {}
        yaw_raw   = float(delta.get("yaw",   0.0))
        pitch_raw = float(delta.get("pitch", 0.0))

        # Gyroscopic damping: shakes decay ~90% within one tick
        self._yaw_damped   += (yaw_raw   - self._yaw_damped)   * _DAMPING
        self._pitch_damped += (pitch_raw - self._pitch_damped) * _DAMPING

        # Field rotation follows the damped yaw; pitch tilts noise sampling
        self._phase += math.radians(self._yaw_damped) * 0.5
        pitch_bias = self._pitch_damped * 0.02

        flat: list[int] = []
        for i in range(_N_VECTORS):
            a = self._phase + i * (2 * math.pi / _N_VECTORS)
            ax = _CX + _RING_R * math.cos(a)
            ay = _CY + _RING_R * math.sin(a)
            # curl of a scalar noise field: rotate the gradient 90°
            n  = _vnoise(i * 3.7 + self._phase * 2.1 + pitch_bias)
            dn = _vnoise(i * 3.7 + self._phase * 2.1 + pitch_bias + 0.5) - n
            ca = a + math.pi / 2 + dn * 1.8       # swirl direction
            ln = _LEN_MIN + (n * 0.5 + 0.5) * (_LEN_MAX - _LEN_MIN)
            x1, y1 = ax - ln * math.cos(ca), ay - ln * math.sin(ca)
            x2, y2 = ax + ln * math.cos(ca), ay + ln * math.sin(ca)
            for x, y in ((x1, y1), (x2, y2)):
                flat.append(_clamp_disp(x, _CX))
                flat.append(_clamp_disp(y, _CY))

        cmd = {"t": "line_field", "v": flat}
        # One MTU frame, guaranteed
        assert len(json.dumps(cmd, separators=(",", ":"))) <= _WIRE_BUDGET
        return cmd

    # ------------------------------------------------------------------
    # Legacy geometry frames (fallback renderer path)
    # ------------------------------------------------------------------

    def tick(self, ctx: RecallContext) -> Optional[dict]:
        """Compute geometry command from IMU delta. Returns BLE cmd or None."""
        if not ctx.has_imu() or ctx.imu_delta is None:
            return None

        delta = ctx.imu_delta
        yaw_rate   = abs(float(delta.get("yaw",   0.0)))
        pitch_rate = abs(float(delta.get("pitch", 0.0)))
        speed = math.sqrt(yaw_rate**2 + pitch_rate**2)

        if speed < _SLOW_THRESHOLD:
            return None   # too slow to bother

        now = time.monotonic()
        if speed >= _FAST_THRESHOLD:
            if (now - self._last_scatter_t) >= _SCATTER_COOLDOWN:
                self._last_scatter_t = now
                return {
                    "t":         "geometry",
                    "mode":      "scatter",
                    "intensity": _clamp01((speed - _FAST_THRESHOLD) / 40.0),
                    "yaw_rate":  round(abs(self._yaw_damped), 2),
                    "pitch_rate": round(abs(self._pitch_damped), 2),
                }

        # Medium speed — rotation
        return {
            "t":         "geometry",
            "mode":      "rotate",
            "intensity": _clamp01((speed - _SLOW_THRESHOLD) / (_FAST_THRESHOLD - _SLOW_THRESHOLD)),
            "yaw_rate":  round(abs(self._yaw_damped), 2),
            "pitch_rate": round(abs(self._pitch_damped), 2),
        }


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _clamp_disp(v: float, center: int) -> int:
    """Clamp a coordinate so the vector endpoint stays on the circular
    display (conservative box clamp against _FIELD_R_MAX)."""
    lo, hi = center - _FIELD_R_MAX, center + _FIELD_R_MAX
    return int(max(lo, min(hi, round(v))))
