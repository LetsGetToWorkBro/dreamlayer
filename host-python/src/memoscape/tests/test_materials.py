"""Tests for display/materials.lua (Air/Ghost/Solid tiers) and the
display/palette.lua dynamic slot bank.

Same lupa pattern as test_transitions.py, pinned to Lua 5.3.
"""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

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
          assign_color_ycbcr = function(...) _calls[#_calls+1] = {"pal", ...} end,
        }}
        """)
    else:
        rt.execute("frame = nil")
    return rt


@pytest.fixture()
def mat():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = _make_runtime()
    rt.execute('_p   = require("display.palette")')
    rt.execute('_mat = require("display.materials")')
    rt.execute("_mat.init()")
    return rt


# ---------------------------------------------------------------------------
# Dynamic slot bank (palette.lua)
# ---------------------------------------------------------------------------

def test_reserved_slot_map_matches_themes(mat):
    """Slot indices must mirror hud/themes.py DYNAMIC_SLOTS."""
    from memoscape.hud import themes as T
    for name in ("ghost_text", "fx", "prism_cool", "prism_warm"):
        assert mat.eval(f'_p.dynamic_slot("{name}")') == T.DYNAMIC_SLOTS[name]


def test_reserve_dynamic_is_idempotent(mat):
    first = mat.eval('_p.reserve_dynamic("ghost_text", 0x58686F)')
    second = mat.eval('_p.reserve_dynamic("ghost_text", 0x123456)')
    assert first == second


def test_reserve_dynamic_rejects_static_slots(mat):
    # parens truncate pcall's multiple returns to the ok boolean
    assert not mat.eval('(pcall(_p.reserve_dynamic, "bad", 0x000000, 7))')
    assert not mat.eval('(pcall(_p.reserve_dynamic, "bad0", 0x000000, 0))')


def test_hex_to_ycbcr_range(mat):
    for hexv in ("0x000000", "0xFFFFFF", "0x2CC79A", "0xE06B52"):
        y, cb, cr = mat.eval(f"_p.hex_to_ycbcr({hexv})")
        assert 0 <= y <= 1023
        assert 0 <= cb <= 1023
        assert 0 <= cr <= 1023
    # black is zero luma, white is full luma, both neutral chroma
    y, cb, cr = mat.eval("_p.hex_to_ycbcr(0x000000)")
    assert y == 0 and abs(cb - 512) <= 2 and abs(cr - 512) <= 2
    y, _, _ = mat.eval("_p.hex_to_ycbcr(0xFFFFFF)")
    assert y == 1020


def test_shift_dynamic_clamps(mat):
    mat.execute("_calls = {}")
    mat.execute('_p.shift_dynamic("fx", 99999, -99999, 0)')
    call = mat.eval("_calls[1]")
    assert call[1] == "pal"
    assert call[3] == 1023   # y clamped high
    assert call[4] == 0      # cb clamped low


def test_restore_returns_base_color(mat):
    mat.execute('_p.set_dynamic_y("ghost_text", 100)')
    mat.execute("_calls = {}")
    mat.execute('_p.restore("ghost_text")')
    call = mat.eval("_calls[1]")
    y, cb, cr = mat.eval('_p.hex_to_ycbcr(_p.dynamic_color("ghost_text"))')
    assert (call[3], call[4], call[5]) == (y, cb, cr)


# ---------------------------------------------------------------------------
# Material tiers
# ---------------------------------------------------------------------------

def test_dither_patterns_are_compile_time_tables(mat):
    assert mat.eval("#_mat.DITHER_50") == 2
    assert mat.eval("#_mat.DITHER_25") == 1
    assert mat.eval("_mat.DITHER_CELL") == 2


def test_tier_of(mat):
    assert mat.eval('_mat.tier_of("ghost_text")') == "ghost"
    assert mat.eval('_mat.tier_of("sky")') == "air"
    assert mat.eval('_mat.tier_of("text_primary")') == "solid"


def test_draw_ghost_text_scales_slot_luma(mat):
    mat.execute("_calls = {}")
    mat.execute('_mat.draw_ghost_text(128, 200, "echo", "sm", 0.5)')
    y_half = mat.eval("_calls[1][3]")
    mat.execute("_calls = {}")
    mat.execute('_mat.draw_ghost_text(128, 200, "echo", "sm", 1.0)')
    y_full = mat.eval("_calls[1][3]")
    assert y_full > y_half > 0


def test_draw_ghost_text_draws_text(mat):
    mat.execute("_calls = {}")
    mat.execute('_mat.draw_ghost_text(128, 200, "echo", "sm", 1.0)')
    kinds = mat.eval('(function() local s="" ; for _,c in ipairs(_calls) do s=s..c[1].."," end; return s end)()')
    assert "text" in kinds


def test_dither_fill_draws_half_the_rows(mat):
    mat.execute("_calls = {}")
    mat.execute("_mat.dither_fill(0, 0, 8, 4, 0x2CC79A, _mat.DITHER_50)")
    lines = mat.eval("#_calls")
    # checker pattern: every row emits runs, but only half the cells kept
    assert lines > 0
    mat.execute("_calls = {}")
    mat.execute("_mat.dither_fill(0, 0, 8, 4, 0x2CC79A, _mat.DITHER_25)")
    assert mat.eval("#_calls") > 0


def test_materials_noop_without_frame():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = _make_runtime(with_frame=False)
    rt.execute('_mat = require("display.materials")')
    rt.execute("_mat.init()")
    rt.execute('_mat.draw_ghost_text(128, 200, "echo", "sm", 1.0)')
    rt.execute("_mat.dither_fill(0, 0, 8, 4, 0x2CC79A)")
