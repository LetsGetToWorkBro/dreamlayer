"""Frame budget guard: the heaviest composited frames stay under
DRAW_CALLS_MAX primitive calls and PAL_WRITES_MAX palette writes per
tick. Measured through the integrated device Lua on the raster harness
(RasterDisplay.draw_calls counts every text/line/rect/circle/set_pixel),
so a Lumen effect that quietly blows the 20fps geometry budget breaks CI
before it stutters on glass."""
import pathlib

import pytest

try:
    import lupa  # noqa: F401
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

pytestmark = pytest.mark.skipif(not LUPA_AVAILABLE, reason="lupa required")

REPO = pathlib.Path(__file__).parents[4]

DAY_FRAME = (
    "{ t='horizon', seq=1, paused=0, v={"
    " 450,102, 380,101, 100,101, -60,302,"
    " -300,102, -350,101, -700,102, -860,102,"
    " -1350,222, -2100,212, 580,401, -900,601 } }"
)

OBJECT_CARD = """{
  type = "ObjectRecallCard", object = "KEYS", primary = "Keys",
  place = "Kitchen table", detail = "beside blue notebook",
  last_seen = "Last seen 7:42 PM", confidence = 0.9, origin_deg = 0,
}"""

TESTIMONY_CARD = """{
  type = "TruthLensCard", verdict = "ELEVATED", confidence = 0.72,
  origin = { x = 150, y = 96 },
  stages = {
    { direction = "truthful",  confidence = 0.9 },
    { direction = "deceptive", confidence = 0.8 },
    { direction = "truthful",  confidence = 0.7 },
    { direction = "insufficient" },
    { direction = "deceptive", confidence = 0.9 },
    { direction = "truthful",  confidence = 0.6 },
    { direction = "truthful",  confidence = 0.8 },
    { direction = "deceptive", confidence = 0.7 },
    { direction = "truthful",  confidence = 0.9 },
  },
}"""


def _session():
    from dreamlayer.bridge.lua_raster import LuaRasterHarness
    h = LuaRasterHarness()
    h.execute("__now = 0")
    h.execute('_r  = require("display.renderer")')
    h.execute('_hz = require("display.horizon")')
    h.execute('require("display/dream_renderer")')
    h.execute('_pr = require("display/prism")')
    h.execute("_r.bind(nil, function() return __now end)")
    h.execute("_hz._now_ms = function() return __now end")
    h.sync_dynamic_slots()
    h.execute(f"_hz.on_frame({DAY_FRAME}, 0)")
    return h


def _tick_calls(h, at_ms):
    h.execute(f"__now = {at_ms}")
    h.display.draw_calls = 0
    h.execute("_r.tick()")
    return h.display.draw_calls


def _budget(h):
    return int(h.eval('require("display.animations").DRAW_CALLS_MAX'))


def test_idle_aurora_day_within_budget():
    h = _session()
    worst = max(_tick_calls(h, 1000 + i * 50) for i in range(10))
    assert 0 < worst <= _budget(h)


def test_object_recall_composite_within_budget():
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({OBJECT_CARD})")
    worst = max(_tick_calls(h, 1050 + i * 50) for i in range(1, 24))
    assert 0 < worst <= _budget(h)


def test_testimony_with_spits_within_budget():
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({TESTIMONY_CARD})")
    worst = max(_tick_calls(h, 1050 + i * 50) for i in range(1, 32))
    assert 0 < worst <= _budget(h)


def test_prism_max_intensity_within_budget():
    h = _session()
    h.execute('_pr.on_prism({ active = 1, intensity = 100, symmetry = 12 })')
    worst = 0
    for i in range(12):
        h.display.draw_calls = 0
        h.execute(f"frame.display.clear(0x000000); _pr.draw({i * 50}); "
                  "frame.display.show()")
        worst = max(worst, h.display.draw_calls)
    assert 0 < worst <= _budget(h)


SAVED_CARD = '{ type = "SavedMemoryCard", primary = "House keys" }'

PERSON_CARD = """{
  type = "PersonContextCard", primary = "Jordan",
  why = "Owes you the contract draft", headline = "Sent invoice Wed",
  detail = "Last seen today", confidence = 0.8,
}"""


def test_saved_memory_composite_within_budget():
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({SAVED_CARD})")
    worst = max(_tick_calls(h, 1050 + i * 50) for i in range(1, 24))
    assert 0 < worst <= _budget(h)


def test_person_context_composite_within_budget():
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({PERSON_CARD})")
    worst = max(_tick_calls(h, 1050 + i * 50) for i in range(1, 24))
    assert 0 < worst <= _budget(h)


def test_crossfade_composite_within_budget():
    # the true worst frame: outgoing ObjectRecall receding under an
    # incoming SavedMemory condensing, over the focused horizon
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({OBJECT_CARD})")
    for i in range(1, 20):
        _tick_calls(h, 1050 + i * 50)             # settle into HOLD
    h.execute(f"__now = 2100; _r.show_card({SAVED_CARD})")
    worst = max(_tick_calls(h, 2100 + i * 50) for i in range(1, 12))
    assert 0 < worst <= _budget(h)


def test_font_switches_bounded_per_tick():
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({PERSON_CARD})")
    worst = 0
    for i in range(1, 24):
        h.display.font_calls = 0
        _tick_calls(h, 1050 + i * 50)
        worst = max(worst, h.display.font_calls)
    assert 0 < worst <= 32


def test_palette_writes_within_budget_at_idle():
    h = _session()
    _tick_calls(h, 1000)
    writes = int(h.eval(
        'require("display.palette_animator").writes_last_tick()'))
    limit = int(h.eval('require("display.animations").PAL_WRITES_MAX'))
    assert 0 < writes <= limit
