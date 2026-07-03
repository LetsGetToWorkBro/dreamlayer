"""Meridian Solid typography contract: the Lua width table matches the
reference face's measured advances (so layout math is honest), the device
font seam matches the Python mirror's pixel sizes, fit_size descends the
ladder correctly, and the set_font latch degrades gracefully."""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

try:
    from PIL import ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"

SIZES = {"hero": 22, "xl": 19, "lg": 17, "md": 13, "sm": 10}
SAMPLE = "Kitchen Table 42"


def _rt(with_set_font=True):
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    if with_set_font:
        rt.execute("""
        _fonts = {}
        frame = { display = {
          set_font = function(fid, sz, sc) _fonts[#_fonts+1] = {fid, sz, sc} end,
          text = function(...) end,
        }}
        """)
    else:
        rt.execute("""
        frame = { display = { text = function(...) end } }
        """)
    rt.execute("""
    T  = require("display.typography")
    PR = require("display.primitives")
    PR._reset_font_for_test()
    """)
    return rt


def _measured_advance(px: int) -> float:
    from dreamlayer.bridge.lua_raster import _load_font
    font = _load_font(px)
    try:
        w = font.getlength(SAMPLE)
    except AttributeError:
        w = font.getbbox(SAMPLE)[2]
    return w / len(SAMPLE)


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow required")
def test_avg_w_matches_reference_face():
    rt = _rt()
    for size, px in SIZES.items():
        lua_w = float(rt.eval(f'T.avg_w_with_tracking("{size}", 0)'))
        assert abs(lua_w - _measured_advance(px)) <= 2.0, (size, lua_w)


def test_device_font_sizes_match_mirror_hierarchy():
    rt = _rt()
    for size, px in SIZES.items():
        assert int(rt.eval(f"T.DEVICE_FONT.{size}.sz")) == px


def test_fit_size_descends_the_ladder():
    rt = _rt()
    assert rt.eval('T.fit_size("KEYS", 170)') == "hero"
    # a long place name must drop below hero rather than clip
    assert rt.eval('T.fit_size("Conference room 4B", 170)') != "hero"
    # pathological width: bottoms out at the ladder floor
    assert rt.eval('T.fit_size("Extraordinarily long string here", 40)') == "md"


def test_set_font_is_cached_per_size():
    rt = _rt()
    rt.execute('PR.text_center(128, 100, "a", "lg", 0xFFFFFF)')
    rt.execute('PR.text_center(128, 120, "b", "lg", 0xFFFFFF)')
    rt.execute('PR.text_center(128, 140, "c", "sm", 0xFFFFFF)')
    assert int(rt.eval("#_fonts")) == 2      # lg once, sm once


def test_unsized_text_resolves_to_default():
    rt = _rt()
    rt.execute('PR.text_center(128, 100, "big", "hero", 0xFFFFFF)')
    rt.execute('PR.text_center(128, 120, "plain", nil, 0xFFFFFF)')
    assert int(rt.eval("_fonts[2][2]")) == SIZES["md"]   # snapped back


def test_missing_set_font_latches_off_gracefully():
    rt = _rt(with_set_font=False)
    # must not raise, and must latch so later calls stay silent no-ops
    rt.execute('PR.text_center(128, 100, "a", "hero", 0xFFFFFF)')
    rt.execute('PR.text_center(128, 120, "b", "sm", 0xFFFFFF)')
    assert rt.eval("PR.font_wired()") is False
