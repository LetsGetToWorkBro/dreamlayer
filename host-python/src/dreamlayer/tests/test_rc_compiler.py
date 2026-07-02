"""End-to-end tests for RealityCompiler (6 tests, all sync via compile_sync)."""
import pytest
from dreamlayer.reality_compiler.compiler import RealityCompiler, CompileResult
from dreamlayer.reality_compiler.schema import RoundTimerIntent, IntervalTimerIntent


@pytest.fixture
def rc():
    return RealityCompiler(dry_run=True)


def test_compile_round_timer_returns_result(rc):
    result = rc.compile_sync("3 minute round timer with 20 seconds overtime")
    assert isinstance(result, CompileResult)
    assert isinstance(result.intent, RoundTimerIntent)


def test_compile_round_timer_lua_has_duration(rc):
    result = rc.compile_sync("5 minute round timer")
    assert "300" in result.lua_code
    assert "${" not in result.lua_code


def test_compile_interval_timer(rc):
    result = rc.compile_sync("45 seconds work 15 seconds rest 8 rounds interval")
    assert isinstance(result.intent, IntervalTimerIntent)
    assert result.ok


def test_compile_battery_warning(rc):
    result = rc.compile_sync("battery warning at 15%")
    assert result.ok
    assert "15" in result.lua_code


def test_compile_dry_run_deploy(rc):
    import asyncio
    result = asyncio.run(rc.compile("stopwatch", deploy=True))
    assert result.deploy_result is not None
    assert result.deploy_result.mode == "dry_run"
    assert result.deploy_result.success


def test_compile_unknown_intent_raises(rc):
    with pytest.raises(ValueError):
        rc.compile_sync("make me a sandwich")


def test_compile_summary_output(rc):
    result = rc.compile_sync("simple counter")
    summary = result.summary()
    assert "simple_counter" in summary
    assert "Lua lines" in summary
