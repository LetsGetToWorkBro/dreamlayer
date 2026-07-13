"""test_world_cards_device.py — the World-lens cards render on the device Lua.

Scholar / GlanceChoice / Taste (World lenses, #106/#108/#116) were Python-mirror
only: on the real BLE path composite() found no draw fn and rendered NOTHING —
the black-disc failure class the repo already fixed once for the O3 cards. They
now have device renderers (display/renderer.lua) with the Meridian Solid
materials + Lumen animation, routed through cards.lua + state_machine + the
queue. These drive the *actual* device code on the raster harness — the same
path the goldens use — asserting they draw, stay in budget, are materially rich,
hold still under reduce_motion, and (the test class that would have caught the
gap) that a HOST-built payload reaches pixels over the BLE path.
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

CARDS = {
    "ScholarCard": (
        'C.scholar({ mode="answer", eyebrow="ANSWER",'
        ' primary="Take 400mg twice daily.",'
        ' items={"Max 1200mg per day", "Not with alcohol"} })'
    ),
    "GlanceChoiceCard": (
        'C.glance_choice({ scene="a French menu",'
        ' options={ {label="Translate"}, {label="Best pick"},'
        ' {label="Explain"} } })'
    ),
    "TasteCard": (
        'C.taste({ eyebrow="BEST PICK", primary="Oatly Barista",'
        ' detail="dairy-free - 4.6 stars",'
        ' items={"Almond Breeze - 4.1", "x Whole milk - dairy"} })'
    ),
}


def _session(reduce=False):
    from dreamlayer.bridge.lua_raster import LuaRasterHarness
    h = LuaRasterHarness()
    h.execute("__now = 0")
    h.execute('_r = require("display.renderer")')
    h.execute('_hz = require("display.horizon")')
    h.execute('C  = require("display.cards")')
    h.execute('_set = require("system.settings")')
    h.execute("_r.bind(nil, function() return __now end)")
    h.execute("_hz._now_ms = function() return __now end")
    h.sync_dynamic_slots()
    h.execute(f"_hz.on_frame({DAY_FRAME}, 0)")
    h.execute(f'_set.set("reduce_motion", {"true" if reduce else "false"})')
    return h


def _show(h, ctor, at=1000):
    h.execute(f"__now = {at}; _r.show_card({ctor})")


def _tick(h, at):
    h.execute(f"__now = {at}")
    h.display.draw_calls = 0
    h.execute("_r.tick()")
    return h.display.draw_calls


def _budget(h):
    return int(h.eval('require("display.animations").DRAW_CALLS_MAX'))


@pytest.mark.parametrize("ctype", list(CARDS))
def test_card_renders_within_budget(ctype):
    h = _session(reduce=False)
    _show(h, CARDS[ctype], at=1000)
    worst = max(_tick(h, 1000 + i * 60) for i in range(1, 24))
    assert 0 < worst <= _budget(h), f"{ctype}: worst {worst} > budget {_budget(h)}"


@pytest.mark.parametrize("ctype", list(CARDS))
def test_card_is_materially_rich(ctype):
    h = _session(reduce=False)
    _show(h, CARDS[ctype], at=1000)
    _tick(h, 2000)
    lit = h.display.bright_pixel_count()
    assert lit > 900, f"{ctype}: only {lit} lit pixels — austere, not Solid"


@pytest.mark.parametrize("ctype", list(CARDS))
def test_reduce_motion_hold_is_perfectly_still(ctype):
    h = _session(reduce=True)
    _show(h, CARDS[ctype], at=1000)
    for t in range(1050, 2600, 50):
        _tick(h, t)
    a = h.display.last_frame().tobytes()
    for t in range(2600, 3600, 50):
        _tick(h, t)
    b = h.display.last_frame().tobytes()
    diff = sum(1 for x, y in zip(a, b) if x != y)
    assert diff == 0, f"{ctype}: {diff} pixels moved under reduce_motion"


def test_scholar_unavailable_is_honest_not_a_guess():
    # the "connect a Brain" state must render (ghost cue + message), not blank
    h = _session(reduce=False)
    _show(h, 'C.scholar({ mode="answer", unavailable=true })', at=1000)
    _tick(h, 2000)
    assert h.display.bright_pixel_count() > 900


# ---------------------------------------------------------------------------
# The REAL pipeline: BLE cards never pass through display/cards.lua — the host
# payload lands on renderer.show_card as-is (main.lua process_inbound). This is
# the exact class of test that would have caught these three rendering NOTHING
# on-device: build the payload with the HOST constructor and assert content
# reaches pixels through the device draw fn.
# ---------------------------------------------------------------------------

def _lua_literal(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, dict):
        return "{ " + ", ".join(
            f'["{k}"] = {_lua_literal(val)}' for k, val in v.items()) + " }"
    if isinstance(v, (list, tuple)):
        return "{ " + ", ".join(_lua_literal(x) for x in v) + " }"
    return "nil"


def _lit_in(h, box):
    img = h.display.last_frame().convert("L").crop(box)
    return sum(1 for px in img.tobytes() if px >= 12)  # 'L' image → one byte/pixel


def test_ble_scholar_reaches_pixels():
    from dreamlayer.hud import cards as host_cards
    payload = host_cards.scholar(
        mode="answer", primary="Take 400mg twice daily.",
        items=["Max 1200mg per day", "Not with alcohol"])
    h = _session(reduce=False)
    h.execute(f"__now = 1000; _r.show_card({_lua_literal(payload)})")
    _tick(h, 2000)
    assert h.display.bright_pixel_count() > 900     # not a black disc
    assert _lit_in(h, (30, 90, 226, 200)) > 200     # the body region is lit


def test_ble_glance_choice_nodes_reach_pixels():
    from dreamlayer.hud import cards as host_cards
    payload = host_cards.glance_choice(
        scene="a French menu",
        options=[{"label": "Translate", "lens": "rosetta"},
                 {"label": "Best pick", "lens": "taste"},
                 {"label": "Explain", "lens": "scholar"}])
    h = _session(reduce=False)
    h.execute(f"__now = 1000; _r.show_card({_lua_literal(payload)})")
    _tick(h, 2000)
    # the three nodes sit on the upper arc — that band must carry accent pixels
    assert _lit_in(h, (40, 40, 216, 100)) > 60


def test_ble_taste_reaches_pixels():
    from dreamlayer.hud import cards as host_cards

    class _Item:
        def __init__(self, label, reasons, ok=True):
            self.label, self.reasons, self.ok = label, reasons, ok

    class _Ranking:
        winner = _Item("Oatly Barista", ["dairy-free", "4.6 stars"])
        items = [winner, _Item("Whole milk", ["dairy"], ok=False)]
        unavailable = False

    payload = host_cards.taste(ranking=_Ranking())
    h = _session(reduce=False)
    h.execute(f"__now = 1000; _r.show_card({_lua_literal(payload)})")
    _tick(h, 2000)
    assert h.display.bright_pixel_count() > 900
    assert _lit_in(h, (30, 90, 226, 140)) > 150     # the winner hero region
