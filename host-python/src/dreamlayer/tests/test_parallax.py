"""Tests for display/parallax.lua — IMU-coupled depth. Covers the nil/no-
sensor no-op, depth-class scaling (information at LOCK never moves), the
against-motion shift with clamping inside SAFE_RADIUS, the spring return
home with inertial overshoot, the privacy freeze, and reduce_motion."""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"

TICK = 50


def _rt(imu=True):
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    if imu:
        rt.execute("""
        __imu = nil
        frame = {
          imu_data = function() return __imu end,
          display = { assign_color_ycbcr = function(...) end },
        }
        """)
    else:
        rt.execute("frame = { display = {} }")
    rt.execute("""
    PX = require("display.parallax")
    A  = require("display.animations")
    TR = require("display.transitions")
    PX.reset(); TR.set_reduce_motion(false)
    """)
    return rt


def _pose(rt, pitch, roll):
    rt.execute(f"__imu = {{ pitch = {pitch}, roll = {roll} }}")


def _off(rt, depth):
    x, y = rt.eval(f'PX.offset("{depth}")')
    return float(x), float(y)


def _sweep(rt, n, start_ms, d_roll):
    """n ticks with the head turning at d_roll deg per tick."""
    roll = 0.0
    for i in range(n):
        roll += d_roll
        _pose(rt, 0.0, roll)
        rt.execute(f"PX.tick({start_ms + i * TICK})")
    return start_ms + n * TICK


def test_no_sensor_means_zero_forever():
    rt = _rt(imu=False)
    rt.execute("PX.tick(0); PX.tick(50)")
    assert _off(rt, "air") == (0.0, 0.0)


def test_lock_depth_never_moves():
    rt = _rt()
    _sweep(rt, 8, 0, 10.0)              # 200 deg/s head turn
    assert _off(rt, "lock") == (0.0, 0.0)
    assert _off(rt, "air") != (0.0, 0.0)


def test_layers_shift_against_head_motion_and_scale_by_depth():
    rt = _rt()
    _sweep(rt, 8, 0, 10.0)              # roll increasing -> offset negative
    ax, _ = _off(rt, "air")
    rx, _ = _off(rt, "rim")
    gx, _ = _off(rt, "ring")
    assert ax < 0
    assert abs(rx) < abs(gx) < abs(ax)  # 1px < 2px < 3px scaling
    assert abs(rx) == pytest.approx(abs(ax) / 3.0, abs=1e-6)


def test_offset_clamped_to_air_max():
    rt = _rt()
    _sweep(rt, 10, 0, 40.0)             # violent 800 deg/s shake
    ax, ay = _off(rt, "air")
    assert abs(ax) <= float(rt.eval("A.PAR_MAX_PX.air"))
    assert abs(ay) <= float(rt.eval("A.PAR_MAX_PX.air"))


def test_spring_home_with_inertial_overshoot():
    rt = _rt()
    end = _sweep(rt, 8, 0, 10.0)
    ax0, _ = _off(rt, "air")
    assert ax0 < 0
    # head stops dead: hold the pose, let the EMA decay under the deadband
    seen = []
    for i in range(24):
        rt.execute(f"PX.tick({end + i * TICK})")
        seen.append(_off(rt, "air")[0])
    assert seen[-1] == 0.0                      # settled home
    assert max(seen) > 0.0                      # crossed past zero: inertia
    assert max(seen) <= abs(ax0) * float(rt.eval("A.SPRING_OVERSHOOT_MAX")) \
        + 1e-6


def test_freeze_grips_instantly():
    rt = _rt()
    _sweep(rt, 8, 0, 10.0)
    assert _off(rt, "air") != (0.0, 0.0)
    rt.execute("PX.freeze(true)")
    assert _off(rt, "air") == (0.0, 0.0)
    _sweep(rt, 4, 1000, 10.0)                   # motion while frozen: still 0
    assert _off(rt, "air") == (0.0, 0.0)
    rt.execute("PX.freeze(false)")
    _sweep(rt, 8, 2000, 10.0)
    assert _off(rt, "air") != (0.0, 0.0)        # thawed


def test_reduce_motion_zeroes_offsets():
    rt = _rt()
    rt.execute("TR.set_reduce_motion(true)")
    _sweep(rt, 8, 0, 10.0)
    assert _off(rt, "air") == (0.0, 0.0)


def test_rim_offset_keeps_marks_inside_safe_radius():
    # worst case: rim mark tip at r=110 plus the rim offset must stay
    # inside SAFE_RADIUS=112
    rt = _rt()
    _sweep(rt, 10, 0, 40.0)
    rx, ry = _off(rt, "rim")
    assert 110 + abs(rx) <= 112
    assert 110 + abs(ry) <= 112
