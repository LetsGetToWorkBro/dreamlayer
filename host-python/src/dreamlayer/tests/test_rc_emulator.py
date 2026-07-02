"""Tests for HaloEmulator + EmulatorValidator (8 tests)."""
import pytest
from dreamlayer.reality_compiler.emulator import HaloEmulator
from dreamlayer.reality_compiler.validator import EmulatorValidator
from dreamlayer.reality_compiler.template_library import get as get_template


# ------------------------------------------------------------------
# HaloEmulator — structural / event tests (no lupa required)
# ------------------------------------------------------------------

def test_emulator_records_double_click():
    emu = HaloEmulator()
    emu.start()
    emu.inject_double_click()
    emu.stop()
    assert "double_click" in emu.events_log()


def test_emulator_records_single_click():
    emu = HaloEmulator()
    emu.start()
    emu.inject_single_click()
    emu.stop()
    assert "single_click" in emu.events_log()


def test_emulator_records_bluetooth():
    emu = HaloEmulator()
    emu.start()
    emu.inject_bluetooth(b"\x01")
    emu.stop()
    assert "bluetooth" in emu.events_log()


def test_emulator_display_text_show():
    emu = HaloEmulator()
    emu._display.text("HELLO", 10, 80)
    emu._display.show()
    assert any("HELLO" in t for t, _, _ in emu.shown_texts())


def test_emulator_display_clear():
    emu = HaloEmulator()
    emu._display.text("FOO", 10, 40)
    emu._display.show()
    emu._display.clear()
    emu._display.show()
    assert emu.shown_texts() == []


def test_emulator_bright_pixel_count_after_text():
    emu = HaloEmulator()
    emu._display.text("ROUND", 10, 80)
    emu._display.show()
    assert emu.bright_pixel_count() > 0


# ------------------------------------------------------------------
# EmulatorValidator — structural validation (no lupa required)
# ------------------------------------------------------------------

def test_validator_passes_clean_lua():
    # Fully substituted Lua — no ${} remaining
    lua = """
frame.display.text("READY", 10, 80)
frame.display.show()
while true do frame.sleep(0.5) end
"""
    tmpl = get_template("round_timer")
    validator = EmulatorValidator()
    result = validator.validate(lua, tmpl)
    assert result.passed


def test_validator_warns_on_unsubstituted_vars():
    lua = "local x = ${duration_sec}\nframe.display.show()"
    tmpl = get_template("round_timer")
    validator = EmulatorValidator()
    result = validator.validate(lua, tmpl)
    # Should still pass (warning only) but flag the var
    assert any("Unsubstituted" in w for w in result.warnings)
