"""Tests for ble/telemetry.lua outbound event system.

Uses lupa to load telemetry.lua directly, binds a Python-side
collector as the send_fn, and asserts that events are emitted
with the correct structure.
"""
import pathlib
import pytest

try:
    import lupa
    from lupa import LuaRuntime
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"


def _make_runtime():
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("frame = nil")
    rt.execute("package.loaded['compat.frame_adapter'] = {}")
    return rt


@pytest.fixture()
def tel_rt():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = _make_runtime()
    rt.execute("""
        _tel = require('ble.telemetry')
        _emitted = {}
        _tel.bind(function(msg)
            _emitted[#_emitted + 1] = msg
        end)
    """)
    return rt


# ---------------------------------------------------------------------------
# Event constants exported
# ---------------------------------------------------------------------------

def test_event_constants_exported(tel_rt):
    assert tel_rt.eval("_tel.CARD_SHOWN")      == "CARD_SHOWN"
    assert tel_rt.eval("_tel.CARD_DISMISSED")  == "CARD_DISMISSED"
    assert tel_rt.eval("_tel.PRIVACY_VEIL")  == "PRIVACY_VEIL"
    assert tel_rt.eval("_tel.PRIVACY_RESUMED") == "PRIVACY_RESUMED"
    assert tel_rt.eval("_tel.QUERY_CANCELLED") == "QUERY_CANCELLED"
    assert tel_rt.eval("_tel.BLE_ERROR")       == "BLE_ERROR"


# ---------------------------------------------------------------------------
# emit() sends correct structure
# ---------------------------------------------------------------------------

def test_emit_card_shown(tel_rt):
    tel_rt.execute("_tel.emit(_tel.CARD_SHOWN, {card_type='ObjectRecallCard', priority=1})")
    msg = tel_rt.eval("_emitted[1]")
    assert msg["t"]         == "TEL"
    assert msg["event"]     == "CARD_SHOWN"
    assert msg["card_type"] == "ObjectRecallCard"
    assert msg["priority"]  == 1
    assert msg["ts"]        >= 0


def test_emit_card_dismissed(tel_rt):
    tel_rt.execute("_tel.emit(_tel.CARD_DISMISSED, {card_type='LoadingCard', method='tap'})")
    msg = tel_rt.eval("_emitted[1]")
    assert msg["event"]     == "CARD_DISMISSED"
    assert msg["card_type"] == "LoadingCard"
    assert msg["method"]    == "tap"


def test_emit_privacy_veil(tel_rt):
    tel_rt.execute("_tel.emit(_tel.PRIVACY_VEIL, {})")
    msg = tel_rt.eval("_emitted[1]")
    assert msg["event"] == "PRIVACY_VEIL"


def test_emit_query_cancelled(tel_rt):
    tel_rt.execute("_tel.emit(_tel.QUERY_CANCELLED, {})")
    assert tel_rt.eval("_emitted[1].event") == "QUERY_CANCELLED"


# ---------------------------------------------------------------------------
# last() reflects most recent emit
# ---------------------------------------------------------------------------

def test_last_returns_nil_before_first_emit(tel_rt):
    # Fresh fixture — nothing emitted yet
    rt = _make_runtime()
    rt.execute("_tel2 = require('ble.telemetry')")
    assert rt.eval("_tel2.last()") is None


def test_last_reflects_most_recent(tel_rt):
    tel_rt.execute("_tel.emit(_tel.CARD_SHOWN, {card_type='ReadyCard'})")
    tel_rt.execute("_tel.emit(_tel.CARD_DISMISSED, {card_type='ReadyCard', method='expire'})")
    last = tel_rt.eval("_tel.last()")
    assert last["event"] == "CARD_DISMISSED"


# ---------------------------------------------------------------------------
# No crash when no send_fn bound
# ---------------------------------------------------------------------------

def test_emit_no_transport_no_crash(tel_rt):
    rt = _make_runtime()
    rt.execute("_tel3 = require('ble.telemetry')")
    # No bind() call — emit must not raise
    rt.execute("_tel3.emit(_tel3.CARD_SHOWN, {card_type='ReadyCard'})")
    assert rt.eval("_tel3.last().event") == "CARD_SHOWN"


# ---------------------------------------------------------------------------
# Multiple emissions accumulate in collector
# ---------------------------------------------------------------------------

def test_multiple_emissions_accumulate(tel_rt):
    for ev in ["CARD_SHOWN", "CARD_DISMISSED", "PRIVACY_VEIL"]:
        tel_rt.execute(f"_tel.emit(_tel.{ev}, {{}})") 
    count = tel_rt.eval("#_emitted")
    assert count == 3
