"""Tests for reality_compiler CodeGenerator + schema validation (10 tests)."""
import pytest
from dreamlayer.reality_compiler.codegen import CodeGenerator
from dreamlayer.reality_compiler.schema import (
    RoundTimerIntent, IntervalTimerIntent, SimpleCounterIntent,
    BatteryWarningIntent, StopwatchIntent, PointsMarkerIntent,
    ReactTimerIntent, ValidationError,
)


@pytest.fixture
def gen():
    return CodeGenerator()


def test_round_timer_lua_contains_duration(gen):
    intent = RoundTimerIntent(duration_sec=180, overtime_sec=30)
    lua, _ = gen.generate(intent)
    assert "180" in lua
    assert "30" in lua


def test_round_timer_no_unsubstituted_vars(gen):
    intent = RoundTimerIntent(duration_sec=120, overtime_sec=0)
    lua, _ = gen.generate(intent)
    assert "${" not in lua


def test_stopwatch_lua_has_running(gen):
    intent = StopwatchIntent()
    lua, _ = gen.generate(intent)
    assert "running" in lua
    assert "RUNNING" in lua or "start" in lua.lower()


def test_interval_timer_has_work_rest(gen):
    intent = IntervalTimerIntent(work_sec=45, rest_sec=15, rounds=8)
    lua, _ = gen.generate(intent)
    assert "45" in lua
    assert "15" in lua
    assert "8" in lua
    assert "WORK" in lua
    assert "REST" in lua


def test_counter_start_value(gen):
    intent = SimpleCounterIntent(start_value=5, increment=2)
    lua, _ = gen.generate(intent)
    assert "5" in lua
    assert "2" in lua


def test_battery_warning_threshold(gen):
    intent = BatteryWarningIntent(threshold_pct=15, warning_color="YELLOW")
    lua, _ = gen.generate(intent)
    assert "15" in lua
    assert "YELLOW" in lua


def test_host_code_has_brilliant_msg(gen):
    intent = RoundTimerIntent()
    _, host = gen.generate(intent)
    assert "BrilliantMsg" in host
    assert "upload_frame_app" in host
    assert "start_frame_app" in host


def test_points_marker_send_to_host(gen):
    intent = PointsMarkerIntent(send_to_host=True)
    lua, _ = gen.generate(intent)
    assert "bluetooth" in lua.lower() or "send" in lua.lower()


def test_validation_error_bad_duration():
    with pytest.raises(ValidationError):
        RoundTimerIntent(duration_sec=5).validate()


def test_validation_error_react_timer_bad_range():
    with pytest.raises(ValidationError):
        ReactTimerIntent(min_delay_ms=5000, max_delay_ms=1000).validate()
