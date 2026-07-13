"""test_dream_weather.py — dream weather must visibly react.

`dream_storm.png` shipped byte-identical to `dream_quiet.png`: the golden
exporter shifted the sky/energy slots through `require("display.palette")`
(the DOT module instance) while dream_renderer reserves them on the SLASH
instance `require("display/palette")` — two separate reservation registries
over the same hardware slots (the footgun documented in
palette_cycle.lua's header). `shift_dynamic("sky")` on the dot instance
found no reservation and silently no-op'd, so storm == quiet.

Nothing compared the two weather frames, so it stayed green for months.
This drives the *actual* device Lua on the raster harness through the REAL
runtime path — `apply_palette_shift({ {idx,y,cb,cr}, … })`, the same call
`main.lua` makes for a `{ t="palette" }` reactor frame — and asserts the
storm frame differs from the quiet frame by a meaningful margin. It uses a
difference threshold, never byte-equality to a committed PNG, so the
procedural particle/AA jitter that (correctly) keeps these frames out of
the deterministic golden set can't flake it.
"""
import pytest

try:
    import lupa  # noqa: F401
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

pytestmark = pytest.mark.skipif(not LUPA_AVAILABLE, reason="lupa required")

DAY_FRAME = (
    "{ t='horizon', seq=1, paused=0, v={"
    " 450,102, 380,101, 100,101, -60,302, -300,102 } }"
)

# a plausible rim-tangent field frame (precomputed, as the host sends)
LINE_FIELD_LUA = """
  local vecs = {}
  for i = 1, 12 do
    local a = (i - 1) * 0.5236 + math.sin(i * 7.13) * 0.45
    local r = 62 + (math.sin(i * 13.7) * 0.5 + 0.5) * 28
    local cx, cy = 128 + r * math.cos(a), 128 + r * math.sin(a)
    local ta = a + 1.5708 + math.sin(i * 3.31) * 0.6
    local ln = 12 + (math.sin(i * 5.77) * 0.5 + 0.5) * 14
    vecs[#vecs+1] = math.floor(cx - ln * math.cos(ta))
    vecs[#vecs+1] = math.floor(cy - ln * math.sin(ta))
    vecs[#vecs+1] = math.floor(cx + ln * math.cos(ta))
    vecs[#vecs+1] = math.floor(cy + ln * math.sin(ta))
  end
  _dr.on_line_field({ v = vecs })
"""

# storm-strength absolute YCbCr on slot 1 (sky) and slot 2 (energy) — the
# exact values the golden exporter now uses.
STORM_SHIFT_LUA = """
  _dr.apply_palette_shift({
    { idx = 1, y = 600, cb = 760, cr = 440 },
    { idx = 2, y = 760, cb = 440, cr = 820 },
  })
"""


def _boot():
    from dreamlayer.bridge.lua_raster import LuaRasterHarness
    h = LuaRasterHarness()
    h.execute("__now = 0")
    h.execute('_hz = require("display.horizon")')
    h.execute('_dr = require("display.dream_renderer")')
    h.execute("_hz._now_ms = function() return __now end")
    h.sync_dynamic_slots()
    h.execute("__now = 1000")
    h.execute(f"_hz.on_frame({DAY_FRAME}, __now)")
    h.execute(LINE_FIELD_LUA)
    # seed _last_now_ms = 1000 so a later apply_palette_shift holds the idle
    # sky-cycle off the slots through the now=2000 render (_reactor_until=2200)
    h.execute("_dr.draw_frame(__now)")
    return h


def _render(h, at=2000):
    h.execute(f"__now = {at}")
    h.execute("frame.display.clear(0x000000); _dr.draw_frame(__now); frame.display.show()")
    return h.display.last_frame().convert("RGB").tobytes()


def _diff(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def test_storm_visibly_differs_from_quiet():
    """One harness, identical particle seed and positions: the only thing
    that changes between the two frames is the palette weather. If the
    index path didn't reach the drawn field, the diff would be ~0 (the
    original bug)."""
    h = _boot()
    quiet = _render(h, at=2000)
    h.execute(STORM_SHIFT_LUA)
    storm = _render(h, at=2000)
    d = _diff(quiet, storm)
    assert d > 300, (
        f"storm differs from quiet by only {d} px — weather did not react "
        "(the dot-vs-slash palette-instance no-op is back)"
    )


def test_index_shift_reaches_the_drawn_field():
    """Pin the footgun directly: the DOT-instance shift_dynamic that the
    old exporter used is a no-op on these slots, while the index-based
    apply_palette_shift the runtime actually uses recolours the field."""
    # DOT instance: shift_dynamic on the slots dream_renderer reserved on
    # the SLASH instance — must find no reservation (the silent no-op).
    h = _boot()
    base = _render(h, at=2000)
    h.execute(
        'local P = require("display.palette")'
        ' P.shift_dynamic("sky", 80, 240, -80)'
        ' P.shift_dynamic("energy", 200, -80, 300)'
    )
    dot = _render(h, at=2000)
    assert _diff(base, dot) == 0, (
        "the dot-instance shift_dynamic changed pixels — the two palette "
        "module instances are no longer separate (test premise broken)"
    )

    # SLASH/index instance: the real runtime path — must recolour the field.
    h2 = _boot()
    b2 = _render(h2, at=2000)
    h2.execute(STORM_SHIFT_LUA)
    idx = _render(h2, at=2000)
    assert _diff(b2, idx) > 300, "index-based apply_palette_shift did not reach the field"


def test_storm_hold_expires_back_to_idle_cycle():
    """After IDLE_HOLD_MS the idle sky-cycle reclaims the slots — the storm
    is a beat of weather, not a permanent recolour."""
    h = _boot()
    h.execute(STORM_SHIFT_LUA)          # _reactor_until = 1000 + 1200 = 2200
    held = _render(h, at=2000)          # < 2200: storm survives
    reclaimed = _render(h, at=4000)     # > 2200: idle cycle runs again
    assert _diff(held, reclaimed) > 0, "idle sky-cycle never reclaimed the slots"
