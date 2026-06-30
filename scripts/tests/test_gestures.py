"""
pytest tests for halo-lua/app/imu_gesture.lua.

Runs the Lua classifier under lupa (Lua 5.4/5.5 via Python bindings).
Falls back gracefully with a clear skip message if lupa is not installed.

Install: uv add lupa

All tests are pure synthetic IMU streams — no hardware, no BLE.

Design
------
The module is loaded once per test via the gesture_module fixture and
stored as the Lua global _M.  _run_lua builds a self-contained Lua
script that uses _M to create a fresh G instance, feeds the stream, and
stores results in _last_fired.  The script is wrapped in pcall so any
Lua error surfaces immediately instead of silently leaving _last_fired
unchanged from the previous test.

Nothing crosses the Python<->Lua boundary except:
  * scalar config values formatted as Lua literals in the script
  * the _last_fired results table read back via lua.eval()

This sidesteps three lupa gotchas:
  1. lua.table(**kw) silently drops kwargs whose names contain underscores
  2. G.feed from Python is None — lupa does not follow __index metamethods
  3. lua.globals().underscore_name = x does not work reliably

EMA / stream design
-------------------
The EMA seeded=false branch sets value=x on the very first sample, so
the first leg of every stream crosses threshold on sample 1.  Subsequent
legs must travel from the opposite extreme via the filter:
  alpha=0.35, strength=35, threshold=28:  6 samples needed (use 8)
  alpha=0.35, strength=32, threshold=28:  7 samples needed (use 8)
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
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def lua():
    if not HAS_LUPA:
        pytest.skip("lupa not available")
    rt = LuaRuntime(unpack_returned_tuples=False)
    rt.execute(f"""
        package.path = package.path
            .. ";{LUA_ROOT}/?.lua"
            .. ";{LUA_ROOT}/?/init.lua"
    """)
    return rt


@pytest.fixture
def gesture_module(lua):
    """Load a fresh copy of the gesture module into the Lua global _M."""
    lua.execute("package.loaded['app.imu_gesture'] = nil")
    lua.execute("_M = require('app.imu_gesture')")


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def _cfg_to_lua(cfg: dict) -> str:
    parts = []
    for k, v in cfg.items():
        if isinstance(v, bool):
            parts.append(f"  {k} = {'true' if v else 'false'},")
        elif isinstance(v, (int, float)):
            parts.append(f"  {k} = {v},")
        elif isinstance(v, str):
            escaped = v.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'  {k} = "{escaped}",')
    return "\n".join(parts)


def _stream_to_lua(stream) -> str:
    rows = ",\n    ".join(
        f"{{{ax}, {ay}, {az}, {t}}}"
        for ax, ay, az, t in stream
    )
    return f"{{\n    {rows}\n  }}"


def _run_lua(lua, stream, **cfg):
    """
    Create a fresh G from the already-loaded _M global, feed the stream,
    return [(name, confidence), ...].
    Errors inside Lua surface as LuaError (via pcall + assert).
    """
    cfg_fields = _cfg_to_lua(cfg)
    stream_lit = _stream_to_lua(stream)

    script = f"""
      local ok, err = pcall(function()
        local fired = {{}}
        local opts = {{
{cfg_fields}
          on_gesture = function(name, conf)
            fired[#fired + 1] = {{name, conf}}
          end,
        }}
        local G = _M.new(opts)
        local stream = {stream_lit}
        for _, v in ipairs(stream) do
          G:feed(v[1], v[2], v[3], v[4])
        end
        _last_fired = fired
      end)
      assert(ok, err)
    """
    lua.execute(script)
    return _collect_fired(lua)


def _collect_fired(lua):
    fired_ref = lua.eval("_last_fired")
    results = []
    i = 1
    while True:
        entry = fired_ref[i]
        if entry is None:
            break
        results.append((str(entry[1]), float(entry[2])))
        i += 1
    return results


def _names(fired):
    return [f[0] for f in fired]


# ---------------------------------------------------------------------------
# Stream builder helpers
# ---------------------------------------------------------------------------

FPS   = 50
DT_MS = 1000 // FPS   # 20 ms per sample


def _samples(ax=0.0, ay=0.0, az=0.0, count=1, start_ms=0):
    return [(ax, ay, az, start_ms + i * DT_MS) for i in range(count)]


# NOD  (Y-axis: +peak → -peak → rest)
# First leg: EMA snaps to strength on sample 1 → crossing +1 immediately.
# Return leg: needs 6 samples at -35 to cross -28 from +35. Use 8 for margin.
# Total: (5+8+3)*20 = 320 ms
def _nod_stream(start_ms=0, strength=35.0):
    t = start_ms
    s  = _samples(0,  strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0, -strength, 0, 8, t);  t += 8 * DT_MS
    s += _samples(0,  0,        0, 3, t)
    return s


# DOUBLE NOD: + - + - within gesture_window_ms=600 ms
# legs: 5+, 8-, 8+, 8- = 580 ms < 600 ms
def _double_nod_stream(start_ms=0, strength=35.0):
    t = start_ms
    s  = _samples(0,  strength, 0, 5, t);  t += 5 * DT_MS
    s += _samples(0, -strength, 0, 8, t);  t += 8 * DT_MS
    s += _samples(0,  strength, 0, 8, t);  t += 8 * DT_MS
    s += _samples(0, -strength, 0, 8, t);  t += 8 * DT_MS
    s += _samples(0,  0,        0, 3, t)
    return s


# SHAKE  (X-axis: 3 alternating crossings)
# First leg (1 sample): snaps to -strength → crosses -28.
# Legs 2+3: need 7-8 samples each from the opposite extreme.
# Total: (1+8+8)*20 = 340 ms < 600 ms
def _shake_stream(start_ms=0, strength=32.0):
    t = start_ms
    s  = _samples(-strength, 0, 0, 1, t);  t += 1 * DT_MS
    s += _samples( strength, 0, 0, 8, t);  t += 8 * DT_MS
    s += _samples(-strength, 0, 0, 8, t);  t += 8 * DT_MS
    s += _samples( 0,        0, 0, 3, t)
    return s


# GLANCE  (Z-axis: brief +crossing then return within peek_max_ms=350 ms)
# rise=6 reliably crosses threshold_tilt=20 at strength=25.
def _glance_stream(start_ms=0, strength=25.0, duration_ms=120):
    t    = start_ms
    rise = 6
    n    = max(1, duration_ms // DT_MS)
    s  = _samples(0, 0, strength, rise + n, t);  t += (rise + n) * DT_MS
    s += _samples(0, 0, 0,                3, t)
    return s


# TILT  (Z-axis: sustained negative for hold_tilt_ms=400 ms)
# EMA snaps to strength on sample 1 → below threshold_tilt=-20 immediately.
# 500 ms stream fires at ~400 ms.
def _tilt_stream(start_ms=0, strength=-25.0, duration_ms=500):
    t  = start_ms
    n  = max(1, duration_ms // DT_MS)
    s  = _samples(0, 0, strength, n, t);  t += n * DT_MS
    s += _samples(0, 0, 0,        3, t)
    return s


# ---------------------------------------------------------------------------
# Tests: NOD_SAVE
# ---------------------------------------------------------------------------

@requires_lupa
class TestNodSave:
    def test_single_nod_fires(self, lua, gesture_module):
        assert "NOD_SAVE" in _names(_run_lua(lua, _nod_stream()))

    def test_nod_confidence_above_threshold(self, lua, gesture_module):
        for name, conf in _run_lua(lua, _nod_stream()):
            if name == "NOD_SAVE":
                assert conf >= 0.70

    def test_weak_nod_below_threshold_ignored(self, lua, gesture_module):
        assert "NOD_SAVE" not in _names(_run_lua(lua, _nod_stream(strength=5.0)))

    def test_nod_cooldown_prevents_double_fire(self, lua, gesture_module):
        # second nod at t=400 ms; first fires at ~200 ms; gap ~200 ms < cooldown 900 ms
        s = _nod_stream(0) + _nod_stream(400)
        fired = _run_lua(lua, s)
        assert len([f for f in fired if f[0] == "NOD_SAVE"]) == 1

    def test_nod_fires_again_after_cooldown(self, lua, gesture_module):
        # second nod at t=1200 ms; first fires at ~200 ms; gap ~1000 ms > cooldown 900 ms
        s = _nod_stream(0) + _nod_stream(1200)
        fired = _run_lua(lua, s)
        assert len([f for f in fired if f[0] == "NOD_SAVE"]) == 2


# ---------------------------------------------------------------------------
# Tests: DOUBLE_NOD
# ---------------------------------------------------------------------------

@requires_lupa
class TestDoubleNod:
    def test_double_nod_fires(self, lua, gesture_module):
        assert "DOUBLE_NOD" in _names(_run_lua(lua, _double_nod_stream()))

    def test_double_nod_not_shadowed_by_single_nod(self, lua, gesture_module):
        assert "DOUBLE_NOD" in _names(_run_lua(lua, _double_nod_stream()))

    def test_single_nod_does_not_fire_double_nod(self, lua, gesture_module):
        assert "DOUBLE_NOD" not in _names(_run_lua(lua, _nod_stream()))


# ---------------------------------------------------------------------------
# Tests: SHAKE_DISMISS
# ---------------------------------------------------------------------------

@requires_lupa
class TestShakeDismiss:
    def test_shake_fires(self, lua, gesture_module):
        assert "SHAKE_DISMISS" in _names(_run_lua(lua, _shake_stream()))

    def test_shake_confidence_above_threshold(self, lua, gesture_module):
        for name, conf in _run_lua(lua, _shake_stream()):
            if name == "SHAKE_DISMISS":
                assert conf >= 0.70

    def test_weak_shake_ignored(self, lua, gesture_module):
        assert "SHAKE_DISMISS" not in _names(_run_lua(lua, _shake_stream(strength=5.0)))

    def test_shake_cooldown(self, lua, gesture_module):
        # second shake at t=400ms; first fires at ~340ms; gap ~60ms < 900ms
        s = _shake_stream(0) + _shake_stream(400)
        fired = _run_lua(lua, s)
        assert len([f for f in fired if f[0] == "SHAKE_DISMISS"]) == 1


# ---------------------------------------------------------------------------
# Tests: GLANCE_PEEK
# ---------------------------------------------------------------------------

@requires_lupa
class TestGlancePeek:
    def test_glance_fires(self, lua, gesture_module):
        assert "GLANCE_PEEK" in _names(_run_lua(lua, _glance_stream()))

    def test_long_tilt_not_glance(self, lua, gesture_module):
        assert "GLANCE_PEEK" not in _names(_run_lua(lua, _glance_stream(duration_ms=600)))


# ---------------------------------------------------------------------------
# Tests: TILT_REVEAL
# ---------------------------------------------------------------------------

@requires_lupa
class TestTiltReveal:
    def test_tilt_fires_when_held(self, lua, gesture_module):
        assert "TILT_REVEAL" in _names(_run_lua(lua, _tilt_stream(duration_ms=500)))

    def test_brief_tilt_does_not_fire(self, lua, gesture_module):
        assert "TILT_REVEAL" not in _names(_run_lua(lua, _tilt_stream(duration_ms=200)))


# ---------------------------------------------------------------------------
# Tests: noise immunity
# ---------------------------------------------------------------------------

@requires_lupa
class TestNoiseImmunity:
    def test_flat_zero_fires_nothing(self, lua, gesture_module):
        assert _run_lua(lua, _samples(0, 0, 0, 100, 0)) == []

    def test_low_noise_fires_nothing(self, lua, gesture_module):
        import random
        rng = random.Random(42)
        stream = [(rng.uniform(-8, 8), rng.uniform(-8, 8), rng.uniform(-8, 8), i * DT_MS)
                  for i in range(150)]
        assert _run_lua(lua, stream) == []

    def test_reset_clears_state(self, lua, gesture_module):
        script = f"""
          local ok, err = pcall(function()
            local fired = {{}}
            local G = _M.new({{on_gesture = function(n,c) fired[#fired+1]={{n,c}} end}})
            -- +peak only (5 samples snaps EMA, no -peak yet)
            for i = 0, 4 do G:feed(0, 35, 0, i*20) end
            G:reset()
            -- -peak only after reset: no +crossing recorded so NOD_SAVE must not fire
            for i = 0, 7 do G:feed(0, -35, 0, 400 + i*20) end
            _last_fired = fired
          end)
          assert(ok, err)
        """
        lua.execute(script)
        assert "NOD_SAVE" not in _names(_collect_fired(lua))


# ---------------------------------------------------------------------------
# Tests: multi-gesture independence
# ---------------------------------------------------------------------------

@requires_lupa
class TestMultiGesture:
    def test_nod_does_not_trigger_shake(self, lua, gesture_module):
        assert "SHAKE_DISMISS" not in _names(_run_lua(lua, _nod_stream()))

    def test_shake_does_not_trigger_nod(self, lua, gesture_module):
        assert "NOD_SAVE" not in _names(_run_lua(lua, _shake_stream()))

    def test_sequential_nod_then_shake(self, lua, gesture_module):
        nod   = _nod_stream(0)
        # start shake 1000ms after nod ends to clear cooldown
        shake = _shake_stream(nod[-1][3] + 1000)
        fired = _run_lua(lua, nod + shake)
        names = _names(fired)
        assert "NOD_SAVE"      in names
        assert "SHAKE_DISMISS" in names


# ---------------------------------------------------------------------------
# Tests: custom config
# ---------------------------------------------------------------------------

@requires_lupa
class TestCustomConfig:
    def test_higher_threshold_ignores_normal_nod(self, lua, gesture_module):
        # threshold_nod=60: EMA of strength=35 never exceeds 35 < 60 → no crossing
        fired = _run_lua(lua, _nod_stream(strength=35.0), threshold_nod=60)
        assert "NOD_SAVE" not in _names(fired)

    def test_wider_cooldown_prevents_second_gesture(self, lua, gesture_module):
        # cooldown_ms=5000; second nod at t=1200; gap ~1000ms < 5000ms → blocked
        fired = _run_lua(lua, _nod_stream(0) + _nod_stream(1200), cooldown_ms=5000)
        assert len([f for f in fired if f[0] == "NOD_SAVE"]) == 1

    def test_shorter_cooldown_allows_rapid_fire(self, lua, gesture_module):
        # cooldown_ms=100; second nod at t=400; gap ~200ms > 100ms → fires
        fired = _run_lua(lua, _nod_stream(0) + _nod_stream(400), cooldown_ms=100)
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
