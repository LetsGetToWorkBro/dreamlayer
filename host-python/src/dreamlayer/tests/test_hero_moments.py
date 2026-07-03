"""Tests for the Lumen hero moments: promise shatter fires exactly on the
state TRANSITION into shattered (never on replay/reconnect), the wake ring
reveals the day outward from the notch, and the dream door spawns warp
streaks instead of a hard clear."""
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
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;{LUA_ROOT}/app/?.lua;"'
               ' .. package.path')
    rt.execute("""
    _lines, _circles = {}, {}
    frame = { display = {
      line   = function(x0,y0,x1,y1,c) _lines[#_lines+1] = {x0,y0,x1,y1,c} end,
      circle = function(x,y,r,c,f)     _circles[#_circles+1] = {x,y,r,c} end,
      rect = function(...) end, text = function(...) end,
      clear = function(...) end, show = function(...) end,
      assign_color_ycbcr = function(...) end,
    }}
    HZ = require("display.horizon")
    PT = require("display.particles")
    A  = require("display.animations")
    TR = require("display.transitions")
    HZ.reset(); PT.clear(); TR.set_reduce_motion(false)
    """)
    return rt


# promise mark at 45.0 deg: code = kind(2)*100 + state*10 + luma(2)
def _frame(rt, seq, state, now):
    rt.execute(f"HZ.on_frame({{ t='horizon', seq={seq}, paused=0, "
               f"v={{450, {200 + state * 10 + 2}}} }}, {now})")


# ---------------------------------------------------------------------------
# Promise shatter
# ---------------------------------------------------------------------------

def test_shatter_fires_on_transition_only():
    rt = _rt()
    _frame(rt, 1, 4, 1000)                     # cracking
    assert int(rt.eval("PT.live_count()")) == 0
    _frame(rt, 2, 5, 2000)                     # -> shattered: shards fly
    assert int(rt.eval("PT.live_count()")) == int(rt.eval("A.SHARD_N"))
    rt.execute("PT.clear()")
    _frame(rt, 3, 5, 3000)                     # still shattered: no re-break
    assert int(rt.eval("PT.live_count()")) == 0


def test_arriving_already_shattered_never_breaks():
    rt = _rt()
    _frame(rt, 1, 5, 1000)                     # first frame IS shattered
    assert int(rt.eval("PT.live_count()")) == 0


def test_shatter_draws_impact_ring_then_stops():
    rt = _rt()
    _frame(rt, 1, 4, 1000)
    _frame(rt, 2, 5, 2000)
    rt.execute("_circles = {}; HZ.draw({ now_ms = 2050 })")
    within = len(_circles(rt))
    rt.execute(f"_circles = {{}}; HZ.draw({{ now_ms = 2000 + "
               f"{int(rt.eval('A.SHATTER_FLASH_MS'))} + 100 }})")
    after = len(_circles(rt))
    assert within > after                      # the ring bloomed and died


def test_shatter_reduce_motion_is_todays_still_pose():
    # a shattered promise reached via the transition must render exactly
    # like one that was already shattered — the transition adds nothing
    # under reduce_motion (no shards, no impact ring)
    rt = _rt()
    rt.execute("TR.set_reduce_motion(true)")
    _frame(rt, 1, 4, 1000)
    _frame(rt, 2, 5, 2000)                        # the transition
    assert int(rt.eval("PT.live_count()")) == 0   # shards no-op
    rt.execute("_circles = {}; HZ.draw({ now_ms = 2050, reduce_motion = true })")
    transitioned = len(_circles(rt))

    rt2 = _rt()
    rt2.execute("TR.set_reduce_motion(true)")
    _frame(rt2, 1, 5, 2000)                       # born shattered
    rt2.execute("_circles = {}; HZ.draw({ now_ms = 2050, reduce_motion = true })")
    assert transitioned == len(_circles(rt2))     # no impact ring added


def _circles(rt):
    return list(rt.eval("_circles").values())


def _lines(rt):
    return list(rt.eval("_lines").values())


# ---------------------------------------------------------------------------
# Wake ring
# ---------------------------------------------------------------------------

def _day(rt, now):
    rt.execute(f"HZ.on_frame({{ t='horizon', seq=1, paused=0, "
               f"v={{450,102, -1350,222, -300,102}} }}, {now})")


def test_wake_reveals_the_day_outward_from_the_notch():
    rt = _rt()
    _day(rt, 1000)
    rt.execute("HZ.wake(2000)")
    rt.execute("_lines = {}; HZ.draw({ now_ms = 2050 })")
    early = len(_lines(rt))
    rt.execute("_lines = {}; HZ.draw({ now_ms = 2400 })")
    mid = len(_lines(rt))
    rt.execute(f"_lines = {{}}; HZ.draw({{ now_ms = 2000 + "
               f"{int(rt.eval('A.WAKE_REVEAL_MS'))} + 50 }})")
    full = len(_lines(rt))
    assert early < mid <= full                 # the instrument assembles
    rt.execute("_lines = {}; HZ.draw({ now_ms = 9000 })")
    assert len(_lines(rt)) == full             # reveal is one-shot


def test_wake_reduce_motion_shows_everything_at_once():
    rt = _rt()
    _day(rt, 1000)
    rt.execute("HZ.draw({ now_ms = 1500, reduce_motion = true })")
    baseline = len(_lines(rt))
    rt.execute("HZ.wake(2000)")
    rt.execute("_lines = {}; HZ.draw({ now_ms = 2050, reduce_motion = true })")
    assert len(_lines(rt)) == baseline         # no partial day, ever


# ---------------------------------------------------------------------------
# Dream door
# ---------------------------------------------------------------------------

def test_dream_transition_spawns_warp_streaks():
    rt = _rt()
    rt.execute("""
    halo = nil
    M = require("main")
    DC = require("ble.host_comm_dream")
    """)
    rt.execute("M.tick()")                     # settle
    assert int(rt.eval("PT.live_count()")) == 0
    rt.execute("DC.on_dream_enter({})")
    rt.execute("M.tick()")
    assert int(rt.eval("PT.live_count()")) > 0  # the door opened as light
