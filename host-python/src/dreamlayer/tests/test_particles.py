"""Tests for display/particles.lua — the pooled deterministic particle
system for hero moments: budget enforcement with oldest-first eviction,
closed-form determinism (same seed + same clock = same pixels), TTL cull,
reduce_motion no-op spawns, and headless safety."""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"


def _rt(with_frame=True):
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    if with_frame:
        rt.execute("""
        _draws = {}
        frame = { display = {
          line   = function(x0,y0,x1,y1,c) _draws[#_draws+1] = {"line",x0,y0,x1,y1,c} end,
          circle = function(x,y,r,c,f)     _draws[#_draws+1] = {"circle",x,y,r,c} end,
          rect   = function(...) end, text = function(...) end,
          clear  = function(...) end, show = function(...) end,
          assign_color_ycbcr = function(...) end,
        }}
        """)
    else:
        rt.execute("frame = nil")
    rt.execute("""
    PT = require("display.particles")
    A  = require("display.animations")
    TR = require("display.transitions")
    """)
    return rt


def _draws(rt):
    out = []
    for row in rt.eval("_draws").values():
        out.append(tuple(row.values()))
    return out


def test_budget_never_exceeded():
    rt = _rt()
    rt.execute("PT.burst(128, 128, 12, {t0=0, seed=1})")
    rt.execute("PT.burst(128, 128, 12, {t0=0, seed=2})")
    rt.execute("PT.shards(45, 6, {t0=0, seed=3})")
    assert int(rt.eval("PT.live_count()")) <= int(rt.eval("A.PARTICLE_BUDGET"))


def test_eviction_is_oldest_first():
    rt = _rt()
    rt.execute("PT.burst(128, 128, 20, {t0=0, seed=1, ttl_ms=1000})")
    rt.execute("PT.shards(45, 6, {t0=100, seed=2, ttl_ms=1000})")
    # the shards (newest) must all survive the eviction
    rt.execute("_draws = {}; PT.tick(150)")
    assert int(rt.eval("PT.live_count()")) == 24


def test_same_seed_same_pixels():
    rt1, rt2 = _rt(), _rt()
    for rt in (rt1, rt2):
        rt.execute("PT.burst(128, 128, 12, {t0=0, seed=42})")
        rt.execute("_draws = {}; PT.tick(200)")
    assert _draws(rt1) == _draws(rt2)
    assert len(_draws(rt1)) == 12


def test_different_seed_different_pixels():
    rt1, rt2 = _rt(), _rt()
    rt1.execute("PT.burst(128, 128, 12, {t0=0, seed=1})")
    rt2.execute("PT.burst(128, 128, 12, {t0=0, seed=99})")
    for rt in (rt1, rt2):
        rt.execute("_draws = {}; PT.tick(200)")
    assert _draws(rt1) != _draws(rt2)


def test_ttl_culls_expired_particles():
    rt = _rt()
    rt.execute("PT.burst(128, 128, 8, {t0=0, seed=1, ttl_ms=300})")
    rt.execute("PT.tick(200)")
    assert int(rt.eval("PT.live_count()")) == 8
    rt.execute("PT.tick(400)")
    assert int(rt.eval("PT.live_count()")) == 0


def test_dots_shrink_as_they_age():
    rt = _rt()
    rt.execute("PT.burst(128, 128, 4, {t0=0, seed=1, ttl_ms=400})")
    rt.execute("_draws = {}; PT.tick(50)")
    young = [d for d in _draws(rt) if d[0] == "circle"]
    rt.execute("PT.burst(128, 128, 4, {t0=0, seed=1, ttl_ms=400})")
    rt.execute("_draws = {}; PT.tick(350)")
    old = [d for d in _draws(rt) if d[0] == "circle"]
    assert all(d[3] == 2 for d in young)      # fresh: 2px
    assert all(d[3] == 1 for d in old)        # dying: 1px — honest fade


def test_streaks_accelerate_outward():
    rt = _rt()
    rt.execute("PT.streaks(6, {t0=0, seed=1, ttl_ms=300})")
    rt.execute("_draws = {}; PT.tick(60)")
    early = [d for d in _draws(rt) if d[0] == "line"]
    rt.execute("PT.streaks(6, {t0=0, seed=1, ttl_ms=300})")
    rt.execute("_draws = {}; PT.tick(240)")
    late = [d for d in _draws(rt) if d[0] == "line"]

    def r2(d):  # squared distance of the streak start from center
        return (d[1] - 128) ** 2 + (d[2] - 128) ** 2
    assert sum(r2(d) for d in late) > sum(r2(d) for d in early)


def test_reduce_motion_spawns_nothing():
    rt = _rt()
    rt.execute("TR.set_reduce_motion(true)")
    rt.execute("PT.burst(128, 128, 12, {t0=0, seed=1})")
    rt.execute("PT.shards(45, 6, {t0=0, seed=1})")
    rt.execute("PT.streaks(18, {t0=0, seed=1})")
    assert int(rt.eval("PT.live_count()")) == 0


def test_headless_is_safe():
    rt = _rt(with_frame=False)
    rt.execute("PT.burst(128, 128, 12, {t0=0, seed=1})")
    rt.execute("PT.tick(100)")   # must not raise
    assert int(rt.eval("PT.live_count()")) == 12
