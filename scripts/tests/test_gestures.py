"""
pytest tests for halo-lua/app/imu_gesture.lua.

Runs the Lua classifier under lupa (Lua 5.4/5.5 via Python bindings).
Falls back gracefully with a clear skip message if lupa is not installed.

Install: uv add lupa

All tests are pure synthetic IMU streams — no hardware, no BLE.

Lupa notes
----------
* lua55 always returns require() as (table, path) — _lua_require unwraps it.
* lupa does NOT follow __index metamethods when accessing table fields from
  Python.  G.feed / G.reset are inherited via __index = M, so they appear
  as None from Python.  All method calls on gesture instances are therefore
  made from Lua-side helpers (_run_lua_stream, _lua_reset) rather than from
  Python directly.
* lupa silently drops Python kwargs whose names contain underscores when
  building Lua tables via lua.table(**kw).  All opts tables are constructed
  as Lua literals via rt.execute() and read back as globals (_build_lua_opts).

EMA / stream design
-------------------
No EMA seeding or priming samples are used.  With alpha=0.35, feeding
5 samples at ±35 reliably crosses threshold ±28 organically
(EMA: 0→12.25→20.3→25.4→28.9 on sample 4).  Streams are designed so
that every required crossing occurs naturally within the gesture window.
"""
from __future__ import annotations

from pathlib import Path

import pytest

try:
    import lupa  # type: ignore
    from lupa import LuaRuntime
    HAS_LUPA = True
except ImportError:
    HAS_LUPA = False

REPO     = Path(__file__).resolve().parent.parent.parent
LUA_ROOT = REPO / "halo-lua"

requires_lupa = pytest.mark.skipif(
    not HAS_LUPA,
    reason="lupa not installed — run: uv add lupa",
)


# ---------------------------------------------------------------------------
# Runtime + module helpers
# ---------------------------------------------------------------------------

def _lua_require(rt, module: str):
    """require() and always return just the table (lua55 returns a tuple)."""
    result = rt.eval(f"require('{module}')")
    return result[0] if isinstance(result, tuple) else result


@pytest.fixture(scope="module")
def lua():
    if not HAS_LUPA:
        pytest.skip("lupa not available")
    rt = LuaRuntime(unpack_returned_tuples=False)
    rt.execute(f"""
        package.path = package.path .. ";{LUA_ROOT}/?.lua;{LUA_ROOT}/?/init.lua"
    """)
    return rt


@pytest.fixture
def gesture_module(lua):
    lua.execute("package.loaded['app.imu_gesture'] = nil")
    return _lua_require(lua, "app.imu_gesture")


# ---------------------------------------------------------------------------
# Lua opts builder
#
# lupa drops underscore kwargs in lua.table(**kw).  Serialise numeric/bool
# cfg values into a Lua table literal, execute it, read back the global.
# on_gesture is wired separately from the pre-declared _test_on_gesture.
# ---------------------------------------------------------------------------

def _build_lua_opts(lua, **cfg):
    parts = []
    for k, v in cfg.items():
        if isinstance(v, bool):
            parts.append(f"  {k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            parts.append(f"  {k} = {v}")
        elif isinstance(v, str):
            escaped = v.replace('"', '\\"')
            parts.append(f'  {k} = "{escaped}"')
    body = ",\n".join(parts)
    lua.execute(f"_test_opts = {{\n{body}\n}}")
    lua.execute("_test_opts.on_gesture = _test_on_gesture")
    return lua.eval("_test_opts")


# ---------------------------------------------------------------------------
# Collector setup + instance creation
# ---------------------------------------------------------------------------

def _new_with_collector(M, lua, **cfg):
    """
    Declare Lua-side fired collector, build opts, create gesture instance.
    Stores instance as global _test_G so Lua-side helpers can call it.
    Returns fired_ref (Lua table proxy) for _collect().
    """
    lua.execute("""
        _test_fired = {}
        _test_on_gesture = function(name, confidence)
            _test_fired[#_test_fired + 1] = {name, confidence}
        end
    """)
    opts = _build_lua_opts(lua, **cfg)
    lua.execute("")          # flush
    # M.new returns a Lua table; store it as a Lua global so Lua can call methods
    lua.globals()._test_M = M
    lua.globals()._test_opts = opts
    lua.execute("_test_G = _test_M.new(_test_opts)")
    return lua.eval("_test_fired")


def _collect(lua, fired_ref):
    """Convert the Lua-side fired list to Python [(name, confidence), ...]."""
    results = []
    i = 1
    while True:
        entry = fired_ref[i]
        if entry is None:
            break
        results.append((str(entry[1]), float(entry[2])))
        i += 1
    return results


# ---------------------------------------------------------------------------
# Lua-side feed runner
#
# Builds a Lua stream table from Python tuples, then calls G:feed() for
# each sample entirely in Lua, avoiding the __index-from-Python problem.
# ---------------------------------------------------------------------------

def _run_lua_stream(lua, stream):
    """Feed stream into _test_G using a Lua-side loop."""
    # Build Lua stream table literal
    rows = ", ".join(
        f"{{{ax}, {ay}, {az}, {t}}}"
        for ax, ay, az, t in stream
    )
    lua.execute(f"""
        do
            local s = {{{rows}}}
            for _, v in ipairs(s) do
                _test_G:feed(v[1], v[2], v[3], v[4])
            end
        end
    """)


def _lua_reset(lua):
    """Call _test_G:reset() from Lua."""
    lua.execute("_test_G:reset()")


def _run(M, lua, stream, **cfg):
    """One-shot: create instance, feed stream, return [(name, conf), ...]."""
    fired_ref = _new_with_collector(M, lua, **cfg)
    _run_lua_stream(lua, stream)
    return _collect(lua, fired_ref)


# ---------------------------------------------------------------------------
# Stream builder helpers
# ---------------------------------------------------------------------------

FPS   = 50
DT_MS = 1000 // FPS   # 20 ms per sample


def _samples(ax=0.0, ay=0.0, az=0.0, count=1, start_ms=0):
    return [(ax, ay, az, start_ms + i * DT_MS) for i in range(count)]


# NOD  (Y-axis: +peak → -peak → rest)
# alpha=0.35 from 0: sample 4 EMA = 28.9 > threshold 28. 5 samples is safe.
def _nod_stream(start_ms=0, strength=35.0):
    t = start_ms
    s  = _samples(0,  strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0, -strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0,  0,        0, 3, t)
    return s


# DOUBLE NOD: 4 crossings within gesture_window_ms=600 ms
# 4 legs × 5 × 20 ms = 400 ms < 600 ms
def _double_nod_stream(start_ms=0, strength=35.0):
    t = start_ms
    s  = _samples(0,  strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0, -strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0,  strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0, -strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0,  0,        0, 3, t)
    return s


# SHAKE  (X-axis: 3 alternating crossings)
def _shake_stream(start_ms=0, strength=32.0):
    t = start_ms
    s  = _samples(-strength, 0, 0, 5, t);  t += 5 * DT_MS
    s += _samples( strength, 0, 0, 5, t);  t += 5 * DT_MS
    s += _samples(-strength, 0, 0, 5, t);  t += 5 * DT_MS
    s += _samples( 0,        0, 0, 3, t)
    return s


# GLANCE  (Z-axis: brief +crossing then return within peek_max_ms=350)
def _glance_stream(start_ms=0, strength=25.0, duration_ms=120):
    t    = start_ms
    rise = 4
    n    = max(1, duration_ms // DT_MS)
    s  = _samples(0, 0, strength, rise + n, t);  t += (rise + n) * DT_MS
    s += _samples(0, 0, 0,                3, t)
    return s


# TILT  (Z-axis: sustained negative for hold_tilt_ms=400 ms)
def _tilt_stream(start_ms=0, strength=-25.0, duration_ms=500):
    t  = start_ms
    n  = max(1, duration_ms // DT_MS)
    s  = _samples(0, 0, strength, n, t);  t += n * DT_MS
    s += _samples(0, 0, 0,        3, t)
    return s


def _names(fired):
    return [f[0] for f in fired]


# ---------------------------------------------------------------------------
# Tests: NOD_SAVE
# ---------------------------------------------------------------------------

@requires_lupa
class TestNodSave:
    def test_single_nod_fires(self, lua, gesture_module):
        assert "NOD_SAVE" in _names(_run(gesture_module, lua, _nod_stream()))

    def test_nod_confidence_above_threshold(self, lua, gesture_module):
        for name, conf in _run(gesture_module, lua, _nod_stream()):
            if name == "NOD_SAVE":
                assert conf >= 0.70

    def test_weak_nod_below_threshold_ignored(self, lua, gesture_module):
        assert "NOD_SAVE" not in _names(_run(gesture_module, lua, _nod_stream(strength=5.0)))

    def test_nod_cooldown_prevents_double_fire(self, lua, gesture_module):
        s = _nod_stream(0) + _nod_stream(200)
        fired = _run(gesture_module, lua, s)
        assert len([f for f in fired if f[0] == "NOD_SAVE"]) == 1

    def test_nod_fires_again_after_cooldown(self, lua, gesture_module):
        s = _nod_stream(0) + _nod_stream(2000)
        fired = _run(gesture_module, lua, s)
        assert len([f for f in fired if f[0] == "NOD_SAVE"]) == 2


# ---------------------------------------------------------------------------
# Tests: DOUBLE_NOD
# ---------------------------------------------------------------------------

@requires_lupa
class TestDoubleNod:
    def test_double_nod_fires(self, lua, gesture_module):
        assert "DOUBLE_NOD" in _names(_run(gesture_module, lua, _double_nod_stream()))

    def test_double_nod_not_shadowed_by_single_nod(self, lua, gesture_module):
        assert "DOUBLE_NOD" in _names(_run(gesture_module, lua, _double_nod_stream()))

    def test_single_nod_does_not_fire_double_nod(self, lua, gesture_module):
        assert "DOUBLE_NOD" not in _names(_run(gesture_module, lua, _nod_stream()))


# ---------------------------------------------------------------------------
# Tests: SHAKE_DISMISS
# ---------------------------------------------------------------------------

@requires_lupa
class TestShakeDismiss:
    def test_shake_fires(self, lua, gesture_module):
        assert "SHAKE_DISMISS" in _names(_run(gesture_module, lua, _shake_stream()))

    def test_shake_confidence_above_threshold(self, lua, gesture_module):
        for name, conf in _run(gesture_module, lua, _shake_stream()):
            if name == "SHAKE_DISMISS":
                assert conf >= 0.70

    def test_weak_shake_ignored(self, lua, gesture_module):
        assert "SHAKE_DISMISS" not in _names(_run(gesture_module, lua, _shake_stream(strength=5.0)))

    def test_shake_cooldown(self, lua, gesture_module):
        s = _shake_stream(0) + _shake_stream(300)
        fired = _run(gesture_module, lua, s)
        assert len([f for f in fired if f[0] == "SHAKE_DISMISS"]) == 1


# ---------------------------------------------------------------------------
# Tests: GLANCE_PEEK
# ---------------------------------------------------------------------------

@requires_lupa
class TestGlancePeek:
    def test_glance_fires(self, lua, gesture_module):
        assert "GLANCE_PEEK" in _names(_run(gesture_module, lua, _glance_stream()))

    def test_long_tilt_not_glance(self, lua, gesture_module):
        assert "GLANCE_PEEK" not in _names(_run(gesture_module, lua, _glance_stream(duration_ms=600)))


# ---------------------------------------------------------------------------
# Tests: TILT_REVEAL
# ---------------------------------------------------------------------------

@requires_lupa
class TestTiltReveal:
    def test_tilt_fires_when_held(self, lua, gesture_module):
        assert "TILT_REVEAL" in _names(_run(gesture_module, lua, _tilt_stream(duration_ms=500)))

    def test_brief_tilt_does_not_fire(self, lua, gesture_module):
        assert "TILT_REVEAL" not in _names(_run(gesture_module, lua, _tilt_stream(duration_ms=200)))


# ---------------------------------------------------------------------------
# Tests: noise immunity
# ---------------------------------------------------------------------------

@requires_lupa
class TestNoiseImmunity:
    def test_flat_zero_fires_nothing(self, lua, gesture_module):
        assert _run(gesture_module, lua, _samples(0, 0, 0, 100, 0)) == []

    def test_low_noise_fires_nothing(self, lua, gesture_module):
        import random
        rng = random.Random(42)
        stream = [(rng.uniform(-8, 8), rng.uniform(-8, 8), rng.uniform(-8, 8), i * DT_MS)
                  for i in range(150)]
        assert _run(gesture_module, lua, stream) == []

    def test_reset_clears_state(self, lua, gesture_module):
        # Feed partial nod (+peak only), reset, feed -peak: should NOT fire
        fired_ref = _new_with_collector(gesture_module, lua)
        _run_lua_stream(lua, _samples(0, 35.0, 0, 5, 0))
        _lua_reset(lua)
        _run_lua_stream(lua, _samples(0, -35.0, 0, 5, 400))
        assert "NOD_SAVE" not in _names(_collect(lua, fired_ref))


# ---------------------------------------------------------------------------
# Tests: multi-gesture independence
# ---------------------------------------------------------------------------

@requires_lupa
class TestMultiGesture:
    def test_nod_does_not_trigger_shake(self, lua, gesture_module):
        assert "SHAKE_DISMISS" not in _names(_run(gesture_module, lua, _nod_stream()))

    def test_shake_does_not_trigger_nod(self, lua, gesture_module):
        assert "NOD_SAVE" not in _names(_run(gesture_module, lua, _shake_stream()))

    def test_sequential_nod_then_shake(self, lua, gesture_module):
        nod   = _nod_stream(0)
        shake = _shake_stream(nod[-1][3] + 1000)
        fired = _run(gesture_module, lua, nod + shake)
        names = _names(fired)
        assert "NOD_SAVE"      in names
        assert "SHAKE_DISMISS" in names


# ---------------------------------------------------------------------------
# Tests: custom config
# ---------------------------------------------------------------------------

@requires_lupa
class TestCustomConfig:
    def test_higher_threshold_ignores_normal_nod(self, lua, gesture_module):
        # threshold_nod=60 > EMA peak ~28.9 → no crossing
        fired = _run(gesture_module, lua, _nod_stream(strength=35.0), threshold_nod=60)
        assert "NOD_SAVE" not in _names(fired)

    def test_wider_cooldown_prevents_second_gesture(self, lua, gesture_module):
        fired = _run(gesture_module, lua, _nod_stream(0) + _nod_stream(2000), cooldown_ms=5000)
        assert len([f for f in fired if f[0] == "NOD_SAVE"]) == 1

    def test_shorter_cooldown_allows_rapid_fire(self, lua, gesture_module):
        fired = _run(gesture_module, lua, _nod_stream(0) + _nod_stream(400), cooldown_ms=100)
        assert len([f for f in fired if f[0] == "NOD_SAVE"]) >= 2


# ---------------------------------------------------------------------------
# Fallback: inform when lupa is absent
# ---------------------------------------------------------------------------

@pytest.mark.skipif(HAS_LUPA, reason="lupa is installed")
def test_lupa_not_installed_inform():
    pytest.skip(
        "Gesture tests require lupa (Lua 5.4/5.5 Python bindings).\n"
        "Install with: uv add lupa\n"
        "Then re-run: uv run pytest scripts/tests/test_gestures.py -v"
    )
