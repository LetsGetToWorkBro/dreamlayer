"""test_prism.py — Prism Lens: the reactive psychedelic kaleidoscope.

Host controller (PrismLens) + the Lua renderer (display/prism.lua) via lupa,
including the message-type lockstep and driving {t="prism"} through the real
booted device loop."""
import pathlib

import pytest

from dreamlayer.dream_mode.prism import PrismLens, MSG_PRISM

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"


# ---------------------------------------------------------------------------
# Host controller
# ---------------------------------------------------------------------------

class TestPrismLens:
    def test_enter_emits_active_frame(self):
        p = PrismLens()
        f = p.enter(intensity=0.5, symmetry=6)
        assert f["t"] == MSG_PRISM and f["active"] == 1
        assert f["intensity"] == 50 and f["symmetry"] == 6

    def test_exit_turns_it_off(self):
        p = PrismLens()
        p.enter()
        assert p.exit() == {"t": MSG_PRISM, "active": 0}
        assert p.active is False

    def test_react_only_emits_on_meaningful_change(self):
        p = PrismLens()
        p.enter(intensity=0.5)
        assert p.react(loudness=0.0, motion=0.0) is None    # already near target
        loud = p.react(loudness=1.0, motion=1.0)            # room gets loud
        assert loud is not None and loud["intensity"] > 50

    def test_react_is_inert_when_off(self):
        assert PrismLens().react(loudness=1.0) is None

    def test_symmetry_is_clamped(self):
        assert PrismLens().enter(symmetry=99)["symmetry"] == 12


# ---------------------------------------------------------------------------
# Lockstep: the wire tag matches the Lua message type
# ---------------------------------------------------------------------------

def test_message_type_lockstep():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute('_mt = require("ble.message_types")')
    assert rt.eval("_mt.PRISM") == MSG_PRISM


# ---------------------------------------------------------------------------
# The Lua renderer
# ---------------------------------------------------------------------------

def _prism_rt():
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _calls = {}
    _pal = {}
    frame = { display = {
      line   = function(...) _calls[#_calls+1] = {"line", ...} end,
      circle = function(...) _calls[#_calls+1] = {"circle", ...} end,
      assign_color_ycbcr = function(slot, y, cb, cr)
        _calls[#_calls+1] = {"pal", slot, y, cb, cr}
        _pal[slot] = { y, cb, cr }
      end,
      clear = function(...) end, show = function(...) end,
    }}
    require("display/dream_renderer")   -- reserves the sky slots prism cycles
    _pr = require("display/prism")
    _pr.reset()
    """)
    return rt


def _counts(rt):
    return rt.eval("""
      (function()
        local n = { line = 0, circle = 0, pal = 0 }
        for _, c in ipairs(_calls) do n[c[1]] = (n[c[1]] or 0) + 1 end
        return n
      end)()
    """)


class TestPrismRenderer:
    @pytest.fixture()
    def rt(self):
        if not LUPA_AVAILABLE:
            pytest.skip("lupa not installed")
        return _prism_rt()

    def test_inactive_draws_nothing(self, rt):
        rt.execute("_calls = {}; _pr.draw(1000)")
        assert int(_counts(rt)["line"]) == 0

    def test_active_draws_a_symmetric_field(self, rt):
        rt.execute('_pr.on_prism({ active = 1, intensity = 60, symmetry = 6 })')
        rt.execute("_calls = {}; _pr.draw(1000)")
        c = _counts(rt)
        assert int(c["line"]) > 0            # arms drawn
        assert int(c["pal"]) > 0             # the palette was cycled
        # more symmetry -> more arms
        rt.execute('_pr.on_prism({ symmetry = 12 })')
        rt.execute("_calls = {}; _pr.draw(1000)")
        assert int(_counts(rt)["line"]) > int(c["line"])

    def test_colour_flows_over_time(self, rt):
        rt.execute('_pr.on_prism({ active = 1, intensity = 60 })')

        def slot1_at(t):
            rt.execute(f"_pal = {{}}; _pr.draw({t})")
            return tuple(int(v) for v in rt.eval("_pal[1]").values())

        assert slot1_at(0) != slot1_at(1500)   # the palette cycle turned

    def test_reduce_motion_is_static(self, rt):
        rt.execute('_pr.on_prism({ active = 1, intensity = 60 })')
        rt.execute("_calls = {}; _pr.draw(1000, { reduce_motion = true })")
        a = rt.eval("#_calls")
        rt.execute("_calls = {}; _pr.draw(9000, { reduce_motion = true })")
        b = rt.eval("#_calls")
        assert a == b and a > 0              # same field, frozen, still drawn

    def test_deactivate_releases(self, rt):
        rt.execute('_pr.on_prism({ active = 1 })')
        assert rt.eval("_pr.is_active()") is True
        rt.execute('_pr.on_prism({ active = 0 })')
        assert rt.eval("_pr.is_active()") is False


# ---------------------------------------------------------------------------
# Through the real booted device loop
# ---------------------------------------------------------------------------

class TestPrismBootChannel:
    @pytest.fixture()
    def dev(self):
        if not LUPA_AVAILABLE:
            pytest.skip("lupa not installed")
        from dreamlayer.tests.test_main_boot import Device
        return Device()

    def test_prism_owns_the_display_when_active(self, dev):
        dev.send({"t": "prism", "active": 1, "intensity": 70, "symmetry": 6})
        dev.ticks(1)
        pr = dev.req("display.prism")
        assert pr["is_active"]() is True
        dev.send({"t": "prism", "active": 0})
        dev.ticks(1)
        assert pr["is_active"]() is False
