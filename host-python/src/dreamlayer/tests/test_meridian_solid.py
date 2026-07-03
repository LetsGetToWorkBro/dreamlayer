"""Meridian Solid — material system and static-richness contracts.

Materials: cost table pinned (the whole point of row-gap panes is that a
translucent disc costs ~40 line calls, not ~4000 pixel calls); gradient
strokes cost exactly a plain stroke; bloom is 2 calls. Tokens: no new
static hex may alias a reserved dynamic-slot base. Richness floors land
with Solid 6 (recomposed cards must exceed pre-Solid lit-pixel counts)."""
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
    _n = { line = 0, circle = 0 }
    frame = { display = {
      line   = function(...) _n.line = _n.line + 1 end,
      circle = function(...) _n.circle = _n.circle + 1 end,
      rect = function(...) end, text = function(...) end,
      set_font = function(...) end,
      clear = function(...) end, show = function(...) end,
      assign_color_ycbcr = function(...) end,
    }}
    MAT = require("display.materials")
    P   = require("display.palette")
    """)
    return rt


# ---------------------------------------------------------------------------
# Cost table (returns AND observed calls agree)
# ---------------------------------------------------------------------------

def test_glass_disc_costs_one_call_per_row():
    rt = _rt()
    calls = int(rt.eval("MAT.glass_disc(128, 112, 62, nil, 3)"))
    assert calls == 41
    assert int(rt.eval("_n.line")) == calls


def test_glass_capsule_cost():
    rt = _rt()
    calls = int(rt.eval("MAT.glass_capsule(64, 100, 128, 32, nil, 3)"))
    assert calls == int(rt.eval("_n.line"))
    assert 9 <= calls <= 11


def test_grad_arc_costs_exactly_a_plain_arc():
    rt = _rt()
    calls = int(rt.eval("MAT.grad_arc(128, 128, 46, 0, 360, nil, 24)"))
    assert calls == 24 == int(rt.eval("_n.line"))


def test_grad_bezier_is_continuous_and_costs_steps():
    rt = _rt()
    calls = int(rt.eval(
        "MAT.grad_bezier(128, 192, 168, 140, 132, 102, nil, 24)"))
    assert calls == 24 == int(rt.eval("_n.line"))   # no dash gaps


def test_grad_line_costs_ramp_length():
    rt = _rt()
    calls = int(rt.eval("MAT.grad_line(76, 164, 180, 164, MAT.RAMP_MEMORY)"))
    assert calls == 4 == int(rt.eval("_n.line"))


def test_bloom_ring_is_two_circles():
    rt = _rt()
    calls = int(rt.eval("MAT.bloom_ring(128, 88, 14, P.memory_trace)"))
    assert calls == 2 == int(rt.eval("_n.circle"))


def test_row_gap_clamps_at_two():
    rt = _rt()
    calls = int(rt.eval("MAT.glass_disc(128, 112, 30, nil, 0)"))
    assert calls <= 30    # gap clamped to 2: never a solid fill


def test_headless_materials_are_noops():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("frame = nil")
    rt.execute('MAT = require("display.materials")')
    assert int(rt.eval("MAT.glass_disc(128, 112, 62)")) == 0
    assert int(rt.eval("MAT.bloom_ring(128, 88, 14, 0x00FFAA)")) == 0


# ---------------------------------------------------------------------------
# Token discipline: no new static hex aliases a reserved dynamic base
# ---------------------------------------------------------------------------

def test_no_solid_token_aliases_a_dynamic_slot_base():
    rt = _rt()
    rt.execute("""
    A = require("display.animations")
    _dyn = { A.SPEC_BASE_A, A.SPEC_BASE_B, A.SPEC_BASE_C,
             A.AURORA_BASE_A, A.AURORA_BASE_B, A.AURORA_BASE_C,
             A.VOICE_BASE, A.PREMO_BASE,
             P.accent_memory,   -- fx base
             P.text_ghost }     -- ghost_text base
    _new = { P.accent_memory_static, P.accent_success_dim,
             P.accent_attention_dim, P.warning_amber_dim, P.surface }
    """)
    dyn = {int(v) for v in rt.eval("_dyn").values()}
    new = [int(v) for v in rt.eval("_new").values()]
    for hexval in new:
        assert hexval not in dyn, hex(hexval)


def test_ramps_never_contain_dynamic_bases():
    rt = _rt()
    rt.execute('A = require("display.animations")')
    fx_base = int(rt.eval("P.accent_memory"))
    ghost_base = int(rt.eval("P.text_ghost"))
    for ramp in ("RAMP_MEMORY", "RAMP_SUCCESS"):
        vals = [int(v) for v in rt.eval(f"MAT.{ramp}").values()]
        assert fx_base not in vals and ghost_base not in vals, ramp


def test_python_mirror_ramps_match_lua():
    rt = _rt()
    from dreamlayer.hud import renderer as R
    lua_mem = [int(v) for v in rt.eval("MAT.RAMP_MEMORY").values()]
    lua_suc = [int(v) for v in rt.eval("MAT.RAMP_SUCCESS").values()]
    assert list(R.RAMP_MEMORY) == lua_mem
    assert list(R.RAMP_SUCCESS) == lua_suc
    assert R.PANE == int(rt.eval("MAT.PANE"))
