"""Tests for the Meridian Lumen spring solver — both the device Lua
(lib/easing.lua spring/anticipate) and its Python twin (hud/motion_math.py),
plus the Lua<->Python parity and the SPRING_OVERSHOOT_MAX contract."""
import math
import pathlib

import pytest

from dreamlayer.hud import motion_math as mm

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"


@pytest.fixture()
def lua():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute('E = require("lib.easing"); A = require("display.animations")')
    return rt


# ---------------------------------------------------------------------------
# Python solver shape
# ---------------------------------------------------------------------------

def test_spring_endpoints():
    assert mm.spring(0.0) == 0.0
    assert mm.spring(1.0) == 1.0
    assert mm.spring(-0.5) == 0.0
    assert mm.spring(2.0) == 1.0


def test_spring_rises_monotonically_before_first_peak():
    prev = 0.0
    for i in range(1, 40):
        t = i * 0.01  # well before the snappy first peak (~0.55)
        v = mm.spring(t, mm.SPRING_ZETA_SNAPPY, mm.SPRING_OMEGA)
        assert v >= prev
        prev = v


def test_snappy_spring_actually_overshoots():
    peak = max(mm.spring(i / 500.0, mm.SPRING_ZETA_SNAPPY, mm.SPRING_OMEGA)
               for i in range(501))
    assert peak > 1.02  # a visible click, not a plain ease


def test_overshoot_cap_holds_for_both_shipped_zetas():
    for zeta in (mm.SPRING_ZETA_SOFT, mm.SPRING_ZETA_SNAPPY,
                 mm.PAR_SPRING_ZETA):
        peak = max(mm.spring(i / 1000.0, zeta, mm.SPRING_OMEGA)
                   for i in range(1001))
        assert peak <= 1.0 + mm.SPRING_OVERSHOOT_MAX, zeta


def test_soft_spring_has_no_visible_overshoot():
    peak = max(mm.spring(i / 500.0, mm.SPRING_ZETA_SOFT, mm.SPRING_OMEGA)
               for i in range(501))
    assert peak <= 1.01


def test_spring_settles_near_one():
    # clamp at t>=1 must not produce a visible jump (sub-pixel for <=100px)
    assert abs(mm.spring(0.999, mm.SPRING_ZETA_SNAPPY) - 1.0) < 0.01


def test_anticipate_pulls_back_then_flies():
    dip = mm.anticipate(mm.ANTICIPATE_FRAC / 2.0)
    assert dip < 0  # pull-back at the window midpoint
    assert mm.anticipate(mm.ANTICIPATE_FRAC) >= 0.0
    assert mm.anticipate(1.0) == 1.0
    assert mm.anticipate(0.0) == 0.0


def test_anticipate_dip_bounded_by_amt():
    lo = min(mm.anticipate(i / 200.0, 0.12, 0.7) for i in range(201))
    assert lo >= -0.7 - 1e-9


# ---------------------------------------------------------------------------
# Lua <-> Python parity (the Lua is the truth; the twin must match it)
# ---------------------------------------------------------------------------

def test_lua_python_spring_parity(lua):
    for i in range(0, 21):
        t = i / 20.0
        for zeta in (0.63, 0.85):
            lv = lua.eval(f"E.spring({t}, {zeta}, 7.4)")
            pv = mm.spring(t, zeta, 7.4)
            assert math.isclose(float(lv), pv, abs_tol=1e-9), (t, zeta)


def test_lua_python_anticipate_parity(lua):
    for i in range(0, 21):
        t = i / 20.0
        lv = lua.eval(f"E.anticipate({t}, 0.12, 1.0)")
        pv = mm.anticipate(t, 0.12, 1.0)
        assert math.isclose(float(lv), pv, abs_tol=1e-9), t


def test_lua_constants_match_python_mirror(lua):
    pairs = {
        "SPRING_OMEGA": mm.SPRING_OMEGA,
        "SPRING_ZETA_SOFT": mm.SPRING_ZETA_SOFT,
        "SPRING_ZETA_SNAPPY": mm.SPRING_ZETA_SNAPPY,
        "SPRING_OVERSHOOT_MAX": mm.SPRING_OVERSHOOT_MAX,
        "ANTICIPATE_FRAC": mm.ANTICIPATE_FRAC,
        "SQUASH_MAX": mm.SQUASH_MAX,
        "PAL_WRITES_MAX": mm.PAL_WRITES_MAX,
        "AURORA_PERIOD_MS": mm.AURORA_PERIOD_MS,
        "AURORA_Y_AMP": mm.AURORA_Y_AMP,
        "AURORA_BASE_A": mm.AURORA_BASE_A,
        "AURORA_BASE_B": mm.AURORA_BASE_B,
        "AURORA_BASE_C": mm.AURORA_BASE_C,
        "SHIMMER_PERIOD_MS": mm.SHIMMER_PERIOD_MS,
        "SHIMMER_Y_LO": mm.SHIMMER_Y_LO,
        "SHIMMER_Y_HI": mm.SHIMMER_Y_HI,
        "PREMO_BASE": mm.PREMO_BASE,
        "TRAIL_SAMPLES": mm.TRAIL_SAMPLES,
        "SPEC_SWEEP_MS": mm.SPEC_SWEEP_MS,
        "SPEC_BASE_A": mm.SPEC_BASE_A,
        "SPEC_BASE_B": mm.SPEC_BASE_B,
        "SPEC_BASE_C": mm.SPEC_BASE_C,
        "VOICE_BASE": mm.VOICE_BASE,
        "CONDUCT_PERIOD_MS": mm.CONDUCT_PERIOD_MS,
        "CHASE_Y_AMP": mm.CHASE_Y_AMP,
        "PAR_RATE_GAIN": mm.PAR_RATE_GAIN,
        "PAR_EMA_ALPHA": mm.PAR_EMA_ALPHA,
        "PAR_SPRING_ZETA": mm.PAR_SPRING_ZETA,
        "PAR_RETURN_MS": mm.PAR_RETURN_MS,
        "PARTICLE_BUDGET": mm.PARTICLE_BUDGET,
        "BURST_N": mm.BURST_N,
        "SHARD_N": mm.SHARD_N,
        "SHATTER_FLASH_MS": mm.SHATTER_FLASH_MS,
        "WAKE_REVEAL_MS": mm.WAKE_REVEAL_MS,
        "WARP_STREAKS": mm.WARP_STREAKS,
        "CHASE_SEGMENTS": mm.CHASE_SEGMENTS,
        "HARK_BREATHE_MS": mm.HARK_BREATHE_MS,
        "HARK_BREATHE_URGENT_MS": mm.HARK_BREATHE_URGENT_MS,
        "FACT_PULSE_MS": mm.FACT_PULSE_MS,
        "PRISM_BLOOM_MS": mm.PRISM_BLOOM_MS,
        "PRISM_BREATH_MS": mm.PRISM_BREATH_MS,
        "PRISM_RING_R_A": mm.PRISM_RING_R_A,
        "PRISM_RING_R_B": mm.PRISM_RING_R_B,
    }
    for name, expect in pairs.items():
        got = lua.eval(f"A.{name}")
        assert float(got) == pytest.approx(float(expect)), name
    for depth in ("rim", "ring", "air"):
        got = lua.eval(f'A.PAR_MAX_PX.{depth}')
        assert int(got) == mm.PAR_MAX_PX[depth], depth


def test_analytic_overshoot_matches_shipped_zeta():
    # exp(-zeta*pi/sqrt(1-zeta^2)) for the snappy zeta stays under the cap
    assert mm.spring_overshoot(mm.SPRING_ZETA_SNAPPY) <= mm.SPRING_OVERSHOOT_MAX
