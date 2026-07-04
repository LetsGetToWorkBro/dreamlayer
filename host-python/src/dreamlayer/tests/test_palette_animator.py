"""Tests for the Meridian Lumen light engine: palette.lua slot leases and
display/palette_animator.lua programs (wave/shimmer/flash/sweep/fade),
the per-tick write budget, reduce_motion still poses, and the strobe
guard — no slot's luma may reverse direction more than 4x per second
(mechanizes the anti-flicker stance that killed temporal dithering)."""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"

TICK_MS = 50


def _rt():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _pal = {}
    frame = { display = {
      assign_color_ycbcr = function(slot, y, cb, cr)
        _pal[slot] = { y, cb, cr }
      end,
    }}
    P  = require("display.palette")
    PA = require("display.palette_animator")
    A  = require("display.animations")
    P.reserve_dynamic("a", 0x2A3C46, 3)
    P.reserve_dynamic("b", 0x2B3D45, 4)
    P.reserve_dynamic("g", 0x58686F, 5)
    P.reserve_dynamic("f", 0x2CC79A, 6)
    """)
    return rt


def _y(rt, slot):
    v = rt.eval(f"_pal[{slot}]")
    return None if v is None else int(v[1])


def _base_y(rt, name):
    return int(rt.eval(f'({{P.hex_to_ycbcr(P.dynamic_color("{name}"))}})[1]'))


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

def test_lease_is_exclusive_per_slot():
    rt = _rt()
    assert rt.eval('P.lease("a", "aurora")') is True
    assert rt.eval('P.lease("a", "someone_else")') is False
    assert rt.eval('P.lease("a", "aurora")') is True   # re-lease self ok
    assert rt.eval('P.owner("a")') == "aurora"


def test_release_restores_base_color():
    rt = _rt()
    rt.execute('P.lease("a", "aurora")')
    rt.execute('P.set_dynamic_y("a", 999)')
    assert _y(rt, 3) == 999
    rt.execute('P.release("aurora")')
    assert _y(rt, 3) == _base_y(rt, "a")
    assert rt.eval('P.owner("a")') is None


def test_run_refused_when_slot_held_elsewhere():
    rt = _rt()
    rt.execute('P.lease("a", "hog")')
    ok = rt.eval('PA.run("aurora", {kind="wave", names={"a","b"}})')
    assert ok is False
    # rollback: b must not be left leased by the failed program
    assert rt.eval('P.owner("b")') is None


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

def test_wave_is_deterministic_and_flows():
    rt = _rt()
    rt.execute('PA.run("aurora", {kind="wave", names={"a","b"}, '
               'period_ms=12000, y_amp=120})')
    rt.execute("PA.tick(1000)")
    at1000 = (_y(rt, 3), _y(rt, 4))
    rt.execute("_pal = {}; PA.tick(4000)")
    at4000 = (_y(rt, 3), _y(rt, 4))
    assert at1000 != at4000                      # the light moved
    rt.execute("_pal = {}; PA.tick(1000)")
    assert (_y(rt, 3), _y(rt, 4)) == at1000      # pure function of now_ms


def test_wave_reduce_motion_holds_base():
    rt = _rt()
    rt.execute('PA.run("aurora", {kind="wave", names={"a","b"}})')
    rt.execute("PA.tick(1234, true)")
    a = (_y(rt, 3), _y(rt, 4))
    rt.execute("_pal = {}; PA.tick(9999, true)")
    assert (_y(rt, 3), _y(rt, 4)) == a
    assert _y(rt, 3) == _base_y(rt, "a")


def test_flash_decays_then_autostops():
    rt = _rt()
    rt.execute('PA.run("hit", {kind="flash", name="f", t0=1000, '
               'dur_ms=150, y_hi=900})')
    rt.execute("PA.tick(1010)")
    early = _y(rt, 6)
    rt.execute("PA.tick(1100)")
    late = _y(rt, 6)
    assert early > late > _base_y(rt, "f") - 1   # decaying toward base
    rt.execute("PA.tick(1200)")                   # past dur: auto-stop
    assert rt.eval('PA.active("hit")') is False
    assert _y(rt, 6) == _base_y(rt, "f")          # restored
    assert rt.eval('P.owner("f")') is None        # lease released


def test_sweep_travels_across_slots_in_order():
    rt = _rt()
    rt.execute('PA.run("spec", {kind="sweep", names={"a","b"}, t0=0, '
               'dur_ms=400, y_amp=360})')
    rt.execute("PA.tick(100)")                    # glint over slot 1
    first = (_y(rt, 3), _y(rt, 4))
    rt.execute("PA.tick(300)")                    # glint over slot 2
    second = (_y(rt, 3), _y(rt, 4))
    assert first[0] > first[1]                    # slot a lit first
    assert second[1] > second[0]                  # then slot b
    rt.execute("PA.tick(500)")
    assert rt.eval('PA.active("spec")') is False  # one-shot


def test_fade_reaches_target_and_reverse_returns():
    rt = _rt()
    rt.execute('PA.run("door", {kind="fade", names={"a","b"}, t0=0, '
               'dur_ms=300, target=0.3})')
    rt.execute("PA.tick(400)")
    assert _y(rt, 3) == pytest.approx(_base_y(rt, "a") * 0.3, abs=2)
    assert rt.eval('PA.active("door")') is True   # holds until stopped
    rt.execute('PA.run("door", {kind="fade", names={"a","b"}, t0=500, '
               'dur_ms=300, target=0.3, reverse=true})')
    rt.execute("PA.tick(900)")
    assert rt.eval('PA.active("door")') is False  # reverse auto-stops
    assert _y(rt, 3) == _base_y(rt, "a")


def test_fade_reduce_motion_sits_at_target():
    # the light level is information (dream = dim terrain); the motion is not
    rt = _rt()
    rt.execute('PA.run("door", {kind="fade", names={"a"}, t0=0, '
               'dur_ms=300, target=0.3})')
    rt.execute("PA.tick(1, true)")
    assert _y(rt, 3) == pytest.approx(_base_y(rt, "a") * 0.3, abs=2)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def test_write_budget_is_enforced_per_tick():
    rt = _rt()
    rt.execute("A.PAL_WRITES_MAX = 2")
    rt.execute('PA.run("aurora", {kind="wave", names={"a","b","g"}})')
    rt.execute('PA.run("shim", {kind="shimmer", name="f"})')
    rt.execute("_pal = {}; PA.tick(1000)")
    assert int(rt.eval("PA.writes_last_tick()")) == 2
    assert _y(rt, 6) is None      # the later program skipped this tick


def test_writes_within_budget_all_land():
    rt = _rt()
    rt.execute('PA.run("aurora", {kind="wave", names={"a","b"}})')
    rt.execute('PA.run("shim", {kind="shimmer", name="g"})')
    rt.execute("PA.tick(1000)")
    assert int(rt.eval("PA.writes_last_tick()")) == 3
    assert int(rt.eval("A.PAL_WRITES_MAX")) >= 3


# ---------------------------------------------------------------------------
# Strobe guard: over any 1-second window (20 ticks at 50ms) a slot's luma
# must not reverse direction more than 4 times. This is the codified
# reason temporal dithering was rejected — nothing we ship may strobe.
# ---------------------------------------------------------------------------

def _direction_reversals(series):
    reversals = 0
    prev_dir = 0
    for a, b in zip(series, series[1:]):
        d = 0 if b == a else (1 if b > a else -1)
        if d != 0 and prev_dir != 0 and d != prev_dir:
            reversals += 1
        if d != 0:
            prev_dir = d
    return reversals


@pytest.mark.parametrize("program", [
    'PA.run("aurora", {kind="wave", names={"a","b","g"}})',
    'PA.run("shim", {kind="shimmer", name="g"})',
    'PA.run("hit", {kind="flash", name="f", t0=0, dur_ms=150, y_hi=900})',
    'PA.run("spec", {kind="sweep", names={"a","b"}, t0=0, dur_ms=420})',
    'PA.run("door", {kind="fade", names={"a"}, t0=0, dur_ms=300, target=0.3})',
])
def test_no_program_strobes(program):
    rt = _rt()
    rt.execute(program)
    series = {3: [], 4: [], 5: [], 6: []}
    for tick in range(0, 40):                     # two 1-second windows
        rt.execute(f"PA.tick({tick * TICK_MS})")
        for slot in series:
            y = _y(rt, slot)
            if y is not None:
                series[slot].append(y)
    for slot, ys in series.items():
        if len(ys) < 20:
            continue
        for start in range(0, len(ys) - 19):
            window = ys[start:start + 20]
            assert _direction_reversals(window) <= 4, (slot, window)
