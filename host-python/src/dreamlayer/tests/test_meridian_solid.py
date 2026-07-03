"""Meridian Solid — material system and static-richness contracts.

Materials: cost table pinned (the whole point of row-gap panes is that a
translucent disc costs ~40 line calls, not ~4000 pixel calls); gradient
strokes cost exactly a plain stroke; bloom is 2 calls. Tokens: no new
static hex may alias a reserved dynamic-slot base. Richness floors land
with Solid 6 (recomposed cards must exceed pre-Solid lit-pixel counts)."""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"


def _rt():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _n = { line = 0, circle = 0 }
    frame = { display = {
      line   = function(...) _n.line = _n.line + 1 end,
      circle = function(...) _n.circle = _n.circle + 1 end,
      rect = function(...) end, text = function(...) end,
      set_font = function(...) end,
      clear = function(...) end, show = function(...) end,
      assign_color_ycbcr = function(...) end,
    }}
    MAT = require("display.materials")
    P   = require("display.palette")
    """)
    return rt


# ---------------------------------------------------------------------------
# Cost table (returns AND observed calls agree)
# ---------------------------------------------------------------------------

def test_glass_disc_costs_one_call_per_row():
    rt = _rt()
    calls = int(rt.eval("MAT.glass_disc(128, 112, 62, nil, 3)"))
    assert calls == 41
    assert int(rt.eval("_n.line")) == calls


def test_glass_capsule_cost():
    rt = _rt()
    calls = int(rt.eval("MAT.glass_capsule(64, 100, 128, 32, nil, 3)"))
    assert calls == int(rt.eval("_n.line"))
    assert 9 <= calls <= 11


def test_grad_arc_costs_exactly_a_plain_arc():
    rt = _rt()
    calls = int(rt.eval("MAT.grad_arc(128, 128, 46, 0, 360, nil, 24)"))
    assert calls == 24 == int(rt.eval("_n.line"))


def test_grad_bezier_is_continuous_and_costs_steps():
    rt = _rt()
    calls = int(rt.eval(
        "MAT.grad_bezier(128, 192, 168, 140, 132, 102, nil, 24)"))
    assert calls == 24 == int(rt.eval("_n.line"))   # no dash gaps


def test_grad_line_costs_ramp_length():
    rt = _rt()
    calls = int(rt.eval("MAT.grad_line(76, 164, 180, 164, MAT.RAMP_MEMORY)"))
    assert calls == 4 == int(rt.eval("_n.line"))


def test_bloom_ring_is_two_circles():
    rt = _rt()
    calls = int(rt.eval("MAT.bloom_ring(128, 88, 14, P.memory_trace)"))
    assert calls == 2 == int(rt.eval("_n.circle"))


def test_row_gap_clamps_at_two():
    rt = _rt()
    calls = int(rt.eval("MAT.glass_disc(128, 112, 30, nil, 0)"))
    assert calls <= 30    # gap clamped to 2: never a solid fill


def test_headless_materials_are_noops():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("frame = nil")
    rt.execute('MAT = require("display.materials")')
    assert int(rt.eval("MAT.glass_disc(128, 112, 62)")) == 0
    assert int(rt.eval("MAT.bloom_ring(128, 88, 14, 0x00FFAA)")) == 0


# ---------------------------------------------------------------------------
# Token discipline: no new static hex aliases a reserved dynamic base
# ---------------------------------------------------------------------------

def test_no_solid_token_aliases_a_dynamic_slot_base():
    rt = _rt()
    rt.execute("""
    A = require("display.animations")
    _dyn = { A.SPEC_BASE_A, A.SPEC_BASE_B, A.SPEC_BASE_C,
             A.AURORA_BASE_A, A.AURORA_BASE_B, A.AURORA_BASE_C,
             A.VOICE_BASE, A.PREMO_BASE,
             P.accent_memory,   -- fx base
             P.text_ghost }     -- ghost_text base
    _new = { P.accent_memory_static, P.accent_success_dim,
             P.accent_attention_dim, P.warning_amber_dim, P.surface }
    """)
    dyn = {int(v) for v in rt.eval("_dyn").values()}
    new = [int(v) for v in rt.eval("_new").values()]
    for hexval in new:
        assert hexval not in dyn, hex(hexval)


def test_ramps_never_contain_dynamic_bases():
    rt = _rt()
    rt.execute('A = require("display.animations")')
    fx_base = int(rt.eval("P.accent_memory"))
    ghost_base = int(rt.eval("P.text_ghost"))
    for ramp in ("RAMP_MEMORY", "RAMP_SUCCESS"):
        vals = [int(v) for v in rt.eval(f"MAT.{ramp}").values()]
        assert fx_base not in vals and ghost_base not in vals, ramp


def test_python_mirror_ramps_match_lua():
    rt = _rt()
    from dreamlayer.hud import renderer as R
    lua_mem = [int(v) for v in rt.eval("MAT.RAMP_MEMORY").values()]
    lua_suc = [int(v) for v in rt.eval("MAT.RAMP_SUCCESS").values()]
    assert list(R.RAMP_MEMORY) == lua_mem
    assert list(R.RAMP_SUCCESS) == lua_suc
    assert R.PANE == int(rt.eval("MAT.PANE"))


# ---------------------------------------------------------------------------
# Richness floors: the whole point of Solid was "the screenshots don't
# look that different". Regenerated goldens/samples must exceed the
# pre-Solid lit-pixel baselines by >=1.25x — a screenshot regression to
# the austere look now breaks CI. Baselines measured from the committed
# assets at the last pre-Solid commit (Lumen 11, branch history).
# ---------------------------------------------------------------------------

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

REPO = pathlib.Path(__file__).parents[4]

RICHNESS_FLOORS = {
    # pre-Solid baseline * 1.25
    "assets/cinema_v2/golden/focus/hold_conf090.png": 4358,      # was 3487
    "assets/cinema_v2/golden/testimony/elevated_mixed.png": 1646, # was 1317
    "assets/hud/samples/object_recall.png": 4076,                # was 3261
    "assets/hud/samples/saved_memory.png": 1795,                 # was 1436
    "assets/hud/samples/person_context.png": 2187,               # was 1750
}


def _lit(path: pathlib.Path) -> int:
    img = Image.open(path).convert("L")
    return sum(img.histogram()[12:])


@pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow required")
def test_solid_frames_are_provably_richer():
    for rel, floor in RICHNESS_FLOORS.items():
        lit = _lit(REPO / rel)
        assert lit > floor, f"{rel}: {lit} lit pixels <= floor {floor}"


# ---------------------------------------------------------------------------
# reduce_motion contracts. The settled composite is NOT pixel-identical
# across the flag (the notch heartbeat freezes and reduce deliberately
# adds a static origin tick in place of the travel motion), so the two
# honest assertions are: (1) under reduce_motion NOTHING moves — two
# settled frames at different times are identical; (2) the Solid
# materials (panes, gradients, blooms) don't vanish under reduce —
# static richness is not motion, so the frame stays comparably lit.
# ---------------------------------------------------------------------------

SOLID_CARDS = {
    "SavedMemoryCard": '{ type = "SavedMemoryCard", primary = "House keys" }',
    "PersonContextCard": """{
      type = "PersonContextCard", primary = "Jordan",
      why = "Owes you the contract draft", headline = "Sent invoice Wed",
      detail = "Last seen today", confidence = 0.8,
    }""",
    "ObjectRecallCard": """{
      type = "ObjectRecallCard", object = "KEYS", primary = "Keys",
      place = "Kitchen table", detail = "beside blue notebook",
      last_seen = "Last seen 7:42 PM", confidence = 0.9, origin_deg = 0,
    }""",
}

DAY_FRAME = ("{ t='horizon', seq=1, paused=0, v={ 450,102, -300,102,"
             " -1350,222 } }")


def _hold_session(card: str, reduce: bool):
    from dreamlayer.bridge.lua_raster import LuaRasterHarness
    h = LuaRasterHarness()
    h.execute("__now = 0")
    h.execute('_r = require("display.renderer")')
    h.execute('_hz = require("display.horizon")')
    h.execute("_r.bind(nil, function() return __now end)")
    h.execute("_hz._now_ms = function() return __now end")
    h.sync_dynamic_slots()
    h.execute(f"_hz.on_frame({DAY_FRAME}, 0)")
    h.execute('_set = require("system.settings")')
    h.execute(f'_set.set("reduce_motion", {"true" if reduce else "false"})')
    h.execute(f"__now = 1000; _r.show_card({card})")
    # far past enter + chime + specular; particles expired
    for t in range(1050, 3500, 50):
        h.execute(f"__now = {t}; _r.tick()")
    return h


def _lit_img(img) -> int:
    return sum(img.convert("L").histogram()[12:])


@pytest.mark.skipif(not (PIL_AVAILABLE and LUPA_AVAILABLE),
                    reason="Pillow + lupa required")
@pytest.mark.parametrize("card_type", sorted(SOLID_CARDS))
def test_reduce_motion_settled_hold_is_perfectly_still(card_type):
    h = _hold_session(SOLID_CARDS[card_type], reduce=True)
    a = h.display.last_frame()
    for t in range(3500, 5000, 50):
        h.execute(f"__now = {t}; _r.tick()")
    b = h.display.last_frame()
    diff = sum(1 for x, y in zip(a.getdata(), b.getdata()) if x != y)
    assert diff == 0, f"{card_type}: {diff} pixels moved under reduce_motion"


@pytest.mark.skipif(not (PIL_AVAILABLE and LUPA_AVAILABLE),
                    reason="Pillow + lupa required")
@pytest.mark.parametrize("card_type", sorted(SOLID_CARDS))
def test_solid_materials_survive_reduce_motion(card_type):
    lit_full = _lit_img(_hold_session(SOLID_CARDS[card_type],
                                      reduce=False).display.last_frame())
    lit_reduce = _lit_img(_hold_session(SOLID_CARDS[card_type],
                                        reduce=True).display.last_frame())
    # panes/gradients/blooms are static richness, not motion: the reduce
    # frame keeps at least 80% of the full frame's light
    assert lit_reduce >= 0.8 * lit_full, (card_type, lit_reduce, lit_full)
