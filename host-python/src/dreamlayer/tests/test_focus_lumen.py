"""Tests for the Lumen focus-law physics (display/focus.lua): the
anticipation pull-back past the rim, the landing ring's spring rebound
below its rest radius, the one-shot hold-ring glint, the phosphor tail
length, and the reduce_motion no-op contract."""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"


def _rt():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _circles, _lines = {}, {}
    frame = { display = {
      circle = function(x,y,r,c,f) _circles[#_circles+1] = {x=x,y=y,r=r,c=c} end,
      line   = function(x0,y0,x1,y1,c) _lines[#_lines+1] = {x0=x0,y0=y0,x1=x1,y1=y1,c=c} end,
      rect = function(...) end, text = function(...) end,
      clear = function(...) end, show = function(...) end,
      assign_color_ycbcr = function(...) end,
    }}
    F  = require("display.focus")
    A  = require("display.animations")
    TR = require("display.transitions")
    TR.set_reduce_motion(false)
    """)
    return rt


def _circles(rt):
    return [dict(row.items()) for row in rt.eval("_circles").values()]


def _lines(rt):
    return [dict(row.items()) for row in rt.eval("_lines").values()]


def test_anticipation_pulls_the_head_past_the_rim():
    rt = _rt()
    # mid-anticipation window: single head, outward of MER_RIM_R
    rt.execute("F.travel(0.06, 0, nil)")   # origin at 0 deg (screen right)
    heads = _circles(rt)
    assert len(heads) == 1
    x = heads[0]["x"] - 128
    assert x > float(rt.eval("A.MER_RIM_R"))   # sunk outward: wind-up


def test_flight_has_squash_and_phosphor_tail():
    rt = _rt()
    rt.execute("F.travel(0.55, 0, nil)")
    n = len(_circles(rt))
    # head + squash lobe + up to TRAIL_SAMPLES tail dots
    assert n >= 4
    assert n <= 2 + int(rt.eval("A.TRAIL_SAMPLES"))


def test_landing_ring_springs_below_rest_radius():
    rt = _rt()
    radii = []
    for i in range(1, 20):
        rt.execute("_lines = {}")
        rt.execute(f"F.landing_ring({i / 20.0}, nil)")
        pts = _lines(rt)
        if pts:
            r = max(abs(p["x0"] - 128) for p in pts)
            radii.append(r)
    assert min(radii) < float(rt.eval("A.SIG_FOCUS_LAND_R_TO"))  # the click
    assert min(radii) >= float(rt.eval("A.SIG_FOCUS_LAND_R_TO")) * (
        1 - float(rt.eval("A.SPRING_OVERSHOOT_MAX"))) - 2


def test_hold_ring_glint_runs_once_then_stops():
    rt = _rt()
    rt.execute("_lines = {}; F.hold_ring(0.9, nil, 100)")   # inside sweep
    with_glint = len(_lines(rt))
    rt.execute("_lines = {}; F.hold_ring(0.9, nil, 5000)")  # long settled
    settled = len(_lines(rt))
    assert with_glint > settled                  # the glint overdraw ended
    rt.execute("_lines = {}; F.hold_ring(0.9, nil, nil)")   # no clock: static
    assert len(_lines(rt)) == settled


def test_hold_ring_settled_is_prelumen_static():
    # after the glint, segment count must match the original formula
    rt = _rt()
    rt.execute("_lines = {}; F.hold_ring(0.9, nil, 5000)")
    sweep = 0.9 * 360
    assert len(_lines(rt)) == max(6, round(sweep / 7.5))


def test_reduce_motion_travel_and_glint_are_noops():
    rt = _rt()
    rt.execute("TR.set_reduce_motion(true)")
    rt.execute("F.travel(0.5, 0, nil)")
    assert _circles(rt) == []
    rt.execute("_lines = {}; F.hold_ring(0.9, nil, 100)")
    static = len(_lines(rt))
    rt.execute("TR.set_reduce_motion(false)")
    rt.execute("_lines = {}; F.hold_ring(0.9, nil, 5000)")
    assert len(_lines(rt)) == static             # identical static ring
