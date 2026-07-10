"""test_forkable_skin.py — Forkable Skin (INNOVATION_SESSION 3.6).

The in-eye design language is data. Pins the theme validator's budget (only the
static identity is restylable — never the dynamic slot bank; type stays in the
font band; motion is bounded), that apply() actually restyles palette +
typography, that both shipped reference themes pass, and that main.lua applies a
boot theme.
"""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

HALO_LUA = Path(__file__).resolve().parents[4] / "halo-lua"


@pytest.fixture
def lua():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{HALO_LUA}/?.lua;" .. package.path')
    return rt


def _theme(lua):
    r = lua.eval('require("display.theme")')
    return r[0] if isinstance(r, tuple) else r


def _tbl(lua, d):
    """Build a Lua table from a (possibly nested) python dict."""
    t = lua.table()
    for k, v in d.items():
        t[k] = _tbl(lua, v) if isinstance(v, dict) else v
    return t


class TestValidate:
    def test_a_clean_theme_passes(self, lua):
        th = _theme(lua)
        ok, issues = th.validate(_tbl(lua, {
            "name": "Test",
            "colors": {"text_primary": 0xFFFFFF, "accent_memory": 0x00FFB0},
            "typography": {"md": {"sz": 14}},
            "motion": {"card_in_ms": 200},
        }))
        assert ok is True and len(issues) == 0

    def test_unknown_color_token_is_refused(self, lua):
        # crucially: a theme cannot name the dynamic slot bank — unknown keys
        # (like 'slot_1' or a made-up token) are rejected outright
        th = _theme(lua)
        ok, issues = th.validate(_tbl(lua, {
            "name": "Bad", "colors": {"slot_1": 0x123456}}))
        assert ok is False and any("dynamic bank" in str(i) for i in issues.values())

    def test_font_outside_the_band_is_refused(self, lua):
        th = _theme(lua)
        ok, issues = th.validate(_tbl(lua, {
            "name": "Huge", "typography": {"hero": {"sz": 40}}}))
        assert ok is False and any("font band" in str(i) for i in issues.values())

    def test_bad_hex_and_motion_are_refused(self, lua):
        th = _theme(lua)
        ok1, _ = th.validate(_tbl(lua, {"name": "X", "colors": {"text_primary": 0x1FFFFFF}}))
        ok2, _ = th.validate(_tbl(lua, {"name": "X", "motion": {"card_in_ms": 9000}}))
        assert ok1 is False and ok2 is False

    def test_nameless_theme_is_refused(self, lua):
        th = _theme(lua)
        ok, _ = th.validate(_tbl(lua, {"colors": {"text_primary": 0xFFFFFF}}))
        assert ok is False


class TestApply:
    def test_apply_restyles_palette_and_type(self, lua):
        th = _theme(lua)
        pal = lua.eval('require("display.palette")')
        typo = lua.eval('require("display.typography")')
        pal = pal[0] if isinstance(pal, tuple) else pal
        typo = typo[0] if isinstance(typo, tuple) else typo
        ok, _ = th.apply(_tbl(lua, {
            "name": "Neon",
            "colors": {"accent_memory": 0xFF2CD4},
            "typography": {"md": {"sz": 15}},
            "motion": {"card_in_ms": 160},
        }))
        assert ok is True
        assert pal.accent_memory == 0xFF2CD4          # palette restyled in place
        assert typo.DEVICE_FONT["md"]["sz"] == 15     # type scale restyled
        assert th.active == "Neon"
        assert th.motion_ms("card_in_ms", 999) == 160
        assert th.motion_ms("missing", 999) == 999    # falls back

    def test_invalid_theme_is_refused_whole(self, lua):
        th = _theme(lua)
        pal = lua.eval('require("display.palette")')
        pal = pal[0] if isinstance(pal, tuple) else pal
        before = pal.text_primary
        ok, _ = th.apply(_tbl(lua, {
            "name": "Broken",
            "colors": {"text_primary": 0x111111, "bogus": 0x222222}}))
        assert ok is False
        assert pal.text_primary == before             # nothing applied partially


class TestReferenceThemes:
    @pytest.mark.parametrize("name", ["cyberpunk", "high_contrast"])
    def test_shipped_themes_pass_the_budget(self, lua, name):
        th = _theme(lua)
        theme = lua.eval(f'require("display.themes.{name}")')
        theme = theme[0] if isinstance(theme, tuple) else theme
        ok, issues = th.validate(theme)
        assert ok is True, list(issues.values())


class TestBoot:
    def test_main_applies_a_boot_theme(self, lua):
        # a host that sets _G.DREAMLAYER_THEME before boot gets it applied
        lua.execute(f'package.path = "{HALO_LUA}/?.lua;{HALO_LUA}/app/?.lua;" .. package.path')
        lua.execute('''
          _G.__rx_queue, _G.__tx = {}, {}
          _G.halo = {
            bluetooth = { receive = function() return nil end,
                          send = function(d) _G.__tx[#_G.__tx+1] = d end },
            display = { text=function() end, clear=function() end, show=function() end },
            battery_level = function() return 88 end,
          }
          _G.DREAMLAYER_THEME = require("display.themes.cyberpunk")
        ''')
        lua.eval('require("main")')
        pal = lua.eval('require("display.palette")')
        theme = lua.eval('require("display.theme")')
        pal = pal[0] if isinstance(pal, tuple) else pal
        theme = theme[0] if isinstance(theme, tuple) else theme
        assert theme.active == "Cyberpunk"
        assert pal.accent_memory == 0xFF2CD4          # the skin took at boot
