"""test_o3_cards_device.py — the O3 conversation cards render on the device Lua.

FactCheck / AnswerAhead / JunoReply / Hark were Python-only; they now have
device renderers (display/renderer.lua) with the Meridian Solid materials and
Lumen animation, routed through cards.lua + state_machine + the queue. These
drive the *actual* device code on the raster harness — the same path the goldens
use — asserting they draw, stay in budget, are materially rich, and hold still
under reduce_motion.
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
    "FactCheckCard": (
        'C.fact_check({ verdict="self_contradiction",'
        ' eyebrow="THEY SAID DIFFERENT BEFORE",'
        ' primary="The deal closed at three million.",'
        ' detail="earlier: we settled at two million",'
        ' footer="Marcus - elevated - seen before" })'
    ),
    "AnswerAheadCard": (
        'C.answer_ahead({ primary="March 14th - two pallets.",'
        ' detail="When did we last ship to Denver?", footer="Priya - your files" })'
    ),
    "JunoReplyCard": (
        'C.juno_reply({ kind="action", primary="Focus on - the world is turned down." })'
    ),
    "HarkCard": (
        'C.hark({ importance="normal", primary="Marcus is 2 min away - you owe him the lease.",'
        ' detail="from your last chat" })'
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
    # reduce_motion is authoritative in settings; show_card re-reads it at ENTER
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
    # sweep the enter + hold window; every frame stays under the draw budget
    worst = max(_tick(h, 1000 + i * 60) for i in range(1, 24))
    assert 0 < worst <= _budget(h), f"{ctype}: worst {worst} > budget {_budget(h)}"


@pytest.mark.parametrize("ctype", list(CARDS))
def test_card_is_materially_rich(ctype):
    h = _session(reduce=False)
    _show(h, CARDS[ctype], at=1000)
    _tick(h, 2000)                      # settle into hold
    lit = h.display.bright_pixel_count()
    assert lit > 900, f"{ctype}: only {lit} lit pixels — austere, not Solid"


@pytest.mark.parametrize("ctype", list(CARDS))
def test_reduce_motion_hold_is_perfectly_still(ctype):
    h = _session(reduce=True)
    _show(h, CARDS[ctype], at=1000)
    # settle deep into hold, past enter + any one-shot settle
    for t in range(1050, 2600, 50):
        _tick(h, t)
    a = h.display.last_frame().tobytes()
    for t in range(2600, 3600, 50):
        _tick(h, t)
    b = h.display.last_frame().tobytes()
    diff = sum(1 for x, y in zip(a, b) if x != y)
    assert diff == 0, f"{ctype}: {diff} pixels moved under reduce_motion"


def _ring_band(h):
    # the "Listen!" cue lives in the top band; crop it so the check isolates
    # the ring from the horizon notch elsewhere on the frame
    img = h.display.last_frame().convert("RGB").crop((96, 42, 160, 76))
    raw = img.tobytes()
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def test_hark_breathes_under_motion():
    h = _session(reduce=False)
    _show(h, CARDS["HarkCard"], at=1000)
    _tick(h, 2000)
    a = _ring_band(h)
    _tick(h, 2350)                      # a different phase of the breathe
    b = _ring_band(h)
    assert a != b, "Hark ring did not breathe on hold"


# ---------------------------------------------------------------------------
# The REAL pipeline: BLE cards never pass through display/cards.lua — the
# host payload lands on renderer.show_card as-is (main.lua process_inbound).
# The standards review of #86 found every BLE-delivered FactCheck rendered
# its verdict cue ghost-gray because the tone mapping lived only in the Lua
# constructors. These tests build the payloads with the HOST constructors
# (hud/cards.py) and assert the verdict/tone color actually reaches pixels.
# ---------------------------------------------------------------------------

def _lua_literal(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            parts.append(f'["{k}"] = {_lua_literal(val)}')
        return "{ " + ", ".join(parts) + " }"
    if isinstance(v, (list, tuple)):
        return "{ " + ", ".join(_lua_literal(x) for x in v) + " }"
    return "nil"


def _rgb(hexval):
    return ((hexval >> 16) & 0xFF, (hexval >> 8) & 0xFF, hexval & 0xFF)


def _has_color(h, hexval, box):
    img = h.display.last_frame().convert("RGB").crop(box)
    raw = img.tobytes()
    px = {tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)}
    return _rgb(hexval) in px


@pytest.mark.parametrize("verdict,tone", [
    ("supported", 0x56D364),            # accent_success
    ("disputed", 0xFF6600),             # warning_amber
    ("self_contradiction", 0xE06B52),   # accent_attention
])
def test_ble_fact_check_verdict_tone_reaches_pixels(verdict, tone):
    from dreamlayer.hud import cards as host_cards
    payload = host_cards.fact_check(
        verdict=verdict, speaker="Marcus",
        claim="The deal closed at three million.",
        basis="earlier: we settled at two million")
    h = _session(reduce=False)
    h.execute(f"__now = 1000; _r.show_card({_lua_literal(payload)})")
    _tick(h, 2000)                       # settled hold
    # the verdict cue band (top of the card)
    assert _has_color(h, tone, (64, 36, 192, 100)), (
        f"BLE-delivered FactCheck '{verdict}' lost its tone — the cue "
        f"band has no {tone:#08x} pixels")


def test_ble_hark_urgent_tone_reaches_pixels():
    from dreamlayer.hud import cards as host_cards
    payload = host_cards.hark(clue="Marcus is 2 min away", detail="lease",
                              importance="urgent")
    h = _session(reduce=False)
    h.execute(f"__now = 1000; _r.show_card({_lua_literal(payload)})")
    _tick(h, 2000)
    assert _has_color(h, 0xFF6600, (64, 36, 192, 110))


def test_ble_juno_action_tone_reaches_pixels():
    from dreamlayer.hud import cards as host_cards
    payload = host_cards.juno_reply(text="Focus on.", kind="action")
    h = _session(reduce=False)
    h.execute(f"__now = 1000; _r.show_card({_lua_literal(payload)})")
    _tick(h, 2000)
    assert _has_color(h, 0x56D364, (32, 40, 224, 110))
