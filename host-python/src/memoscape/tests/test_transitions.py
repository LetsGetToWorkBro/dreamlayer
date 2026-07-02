"""Tests for display/transitions.lua (Halo Cinema v1 motion signatures)
and the Line Field 2.0 host-side generator.

Lua side follows the lupa pattern from test_diagnostics.py, pinned to
Lua 5.3 to match the device runtime. A fake `frame` table records draw
calls so signature geometry is assertable without hardware.
"""
import json
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

from memoscape.app.dream.imu_reactor import ImuReactor, _WIRE_BUDGET
from memoscape.app.recall_context import RecallContext

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"


def _make_runtime(with_frame=True):
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    if with_frame:
        rt.execute("""
        _calls = {}
        frame = { display = {
          line   = function(...) _calls[#_calls+1] = {"line", ...} end,
          rect   = function(...) _calls[#_calls+1] = {"rect", ...} end,
          circle = function(...) _calls[#_calls+1] = {"circle", ...} end,
          text   = function(...) _calls[#_calls+1] = {"text", ...} end,
          bitmap = function(...) end,
          clear  = function(...) end,
          show   = function(...) end,
          assign_color_ycbcr = function(...) _calls[#_calls+1] = {"pal", ...} end,
        }}
        """)
    else:
        rt.execute("frame = nil")
    return rt


@pytest.fixture()
def tr():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = _make_runtime()
    rt.execute('_tr = require("display.transitions")')
    rt.execute('_a  = require("display.animations")')
    return rt


# ---------------------------------------------------------------------------
# Enter durations / reduce_motion contract
# ---------------------------------------------------------------------------

def test_enter_durations_come_from_animations(tr):
    assert tr.eval('_tr.enter_duration("iris")') == \
        tr.eval("_a.SIG_IRIS_MS + _a.SIG_IRIS_TRAIL_MS")
    assert tr.eval('_tr.enter_duration("ghost_wake")') == \
        tr.eval("_a.SIG_GHOSTWAKE_MS")
    assert tr.eval('_tr.enter_duration("ripple")') == \
        tr.eval("_a.SIG_RIPPLE_MS")
    assert tr.eval('_tr.enter_duration("comet")') == \
        tr.eval("_a.SIG_COMET_MS + _a.SIG_IRIS_MS")


def test_reduce_motion_collapses_enter_to_zero(tr):
    tr.execute("_tr.set_reduce_motion(true)")
    assert tr.eval('_tr.enter_duration("iris")') == 0
    assert tr.eval('_tr.enter_duration("comet")') == 0
    tr.execute("_tr.set_reduce_motion(false)")
    assert tr.eval('_tr.enter_duration("iris")') > 0


# ---------------------------------------------------------------------------
# S1 Iris Bloom
# ---------------------------------------------------------------------------

def test_iris_gate_radius_collapses(tr):
    r_early = tr.eval("_tr.iris_bloom(0.1)")
    r_late = tr.eval("_tr.iris_bloom(0.7)")
    assert r_early > r_late
    assert tr.eval("_tr.iris_bloom(1.0)") == 0   # gate fully open


def test_iris_reduce_motion_opens_instantly(tr):
    tr.execute("_tr.set_reduce_motion(true)")
    assert tr.eval("_tr.iris_bloom(0.0)") == 0
    tr.execute("_tr.set_reduce_motion(false)")


# ---------------------------------------------------------------------------
# S6 Memory Comet — entry angle encodes recency
# ---------------------------------------------------------------------------

def test_comet_angle_today_is_12_oclock(tr):
    assert tr.eval("_tr.comet_entry_angle(0)") == -90


def test_comet_angle_sweeps_clockwise_per_week(tr):
    assert tr.eval("_tr.comet_entry_angle(1)") == -60
    assert tr.eval("_tr.comet_entry_angle(4)") == 30


def test_comet_angle_caps(tr):
    assert tr.eval("_tr.comet_entry_angle(99)") == -90 + tr.eval("_a.SIG_COMET_MAX_DEG")


def test_comet_reduce_motion_draws_static_tick(tr):
    tr.execute("_tr.set_reduce_motion(true)")
    tr.execute("_calls = {}")
    tr.execute("_tr.memory_comet(0.5, 2, 128, 118)")
    # exactly one static line (the recency tick), no comet head circle
    assert tr.eval('#_calls') == 1
    assert tr.eval('_calls[1][1]') == "line"
    tr.execute("_tr.set_reduce_motion(false)")


# ---------------------------------------------------------------------------
# Shared exit
# ---------------------------------------------------------------------------

def test_exit_contract_scale_and_text_cut(tr):
    scale, text_ok = tr.eval("_tr.exit_contract(0.2)")
    assert abs(scale - 0.8) < 1e-6 and text_ok
    scale, text_ok = tr.eval("_tr.exit_contract(0.5)")
    assert abs(scale - 0.5) < 1e-6 and not text_ok   # text cuts at t=0.4


def test_exit_contract_reduce_motion_is_hard_cut(tr):
    tr.execute("_tr.set_reduce_motion(true)")
    scale, text_ok = tr.eval("_tr.exit_contract(0.5)")
    assert scale == 1 and text_ok
    scale, text_ok = tr.eval("_tr.exit_contract(1.0)")
    assert scale == 0 and not text_ok
    tr.execute("_tr.set_reduce_motion(false)")


# ---------------------------------------------------------------------------
# S4 Confidence Halo — information preserved under reduce_motion
# ---------------------------------------------------------------------------

def test_confidence_halo_draws_arc(tr):
    tr.execute("_calls = {}")
    tr.execute("_tr.confidence_halo(0, 0.9)")
    assert tr.eval("#_calls") > 0


def test_confidence_halo_static_when_reduce_motion(tr):
    tr.execute("_tr.set_reduce_motion(true)")
    tr.execute("_calls = {}; _tr.confidence_halo(0, 0.5)")
    first = tr.eval("#_calls")
    tr.execute("_calls = {}; _tr.confidence_halo(1600, 0.5)")
    # same draw regardless of idle time: the orbit is frozen
    assert tr.eval("#_calls") == first
    tr.execute("_tr.set_reduce_motion(false)")


# ---------------------------------------------------------------------------
# S2/S3/S5 + acoustics: draw without error, palette slots touched
# ---------------------------------------------------------------------------

def test_ghost_wake_draws_per_character(tr):
    tr.execute("_calls = {}")
    tr.execute('_tr.ghost_wake_text(128, 210, "ECHO", "sm", 0.5, 1234)')
    texts = tr.eval('(function() local n=0; for _,c in ipairs(_calls) do if c[1]=="text" then n=n+1 end end; return n end)()')
    assert texts == 4   # one draw per character


def test_prism_slide_reassigns_fringe_slots(tr):
    tr.execute("_calls = {}")
    tr.execute("_tr.prism_slide(0.3)")
    pals = tr.eval('(function() local n=0; for _,c in ipairs(_calls) do if c[1]=="pal" then n=n+1 end end; return n end)()')
    assert pals >= 2   # prism_cool + prism_warm animated


def test_truth_ripple_and_acoustics_run(tr):
    tr.execute("_tr.truth_ripple(0.4, 128, 96)")
    tr.execute("_tr.truth_ripple_cold(0.4, 128, 96)")
    tr.execute("_tr.chime(0.5)")
    tr.execute("_tr.chord(1.0, 128, 56, 0.8)")
    tr.execute("_tr.rumble(0.5)")


def test_all_signatures_noop_without_frame():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = _make_runtime(with_frame=False)
    rt.execute('_tr = require("display.transitions")')
    rt.execute('_tr.iris_bloom(0.5)')
    rt.execute('_tr.memory_comet(0.5, 1, 128, 128)')
    rt.execute('_tr.confidence_halo(0, 0.5)')
    rt.execute('_tr.ghost_wake_text(128, 210, "x", "sm", 0.5, 0)')


# ---------------------------------------------------------------------------
# Line Field 2.0 (host side, pairs with t="line_field" Lua handler)
# ---------------------------------------------------------------------------

def _imu_ctx(yaw=10.0, pitch=2.0):
    ctx = RecallContext()
    ctx.imu_pose = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
    ctx.imu_delta = {"yaw": yaw, "pitch": pitch}
    return ctx


def test_line_field_fits_one_mtu_frame():
    r = ImuReactor()
    cmd = r.line_field(_imu_ctx())
    wire = json.dumps(cmd, separators=(",", ":"))
    assert len(wire) <= _WIRE_BUDGET


def test_line_field_has_12_vectors():
    r = ImuReactor()
    cmd = r.line_field(_imu_ctx())
    assert cmd["t"] == "line_field"
    assert len(cmd["v"]) == 48   # 12 vectors × 4 coords


def test_line_field_none_without_imu():
    r = ImuReactor()
    assert r.line_field(RecallContext()) is None


def test_line_field_gyroscopic_damping():
    """A single head-shake spike must not swing the field: the damped rate
    keeps ~90% suppressed within one tick."""
    r = ImuReactor()
    r.line_field(_imu_ctx(yaw=100.0))
    assert abs(r._yaw_damped) <= 100.0 * 0.11


def test_line_field_vectors_stay_on_display():
    r = ImuReactor()
    for _ in range(20):
        cmd = r.line_field(_imu_ctx(yaw=50.0, pitch=30.0))
    for coord in cmd["v"]:
        assert 6 <= coord <= 250
