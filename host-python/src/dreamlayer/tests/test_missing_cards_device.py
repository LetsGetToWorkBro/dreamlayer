"""test_missing_cards_device.py — the seven glass-bound cards that used to
render a black frame on the device now have Meridian Solid renderers, PLUS a
structural safety net: any unmapped card type falls back to a legible card
instead of pure black.

Listening / Message / Upcoming / Here / PersonDossier / SpokenCaption /
MorningBrief were all constructed in the orchestrator and sent over BLE
(bridge.send_card), but had no device draw fn — composite()'s
`if not fn then return end` drew nothing. These drive the *actual* device Lua
on the raster harness, and (the test class that would have caught the gap)
build payloads with the HOST constructors and assert content reaches pixels.
"""
import pathlib

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
    "ListeningCard": (
        'C.listening({ source="voice", eyebrow="ORACLE",'
        ' primary="Listening...", detail="woke by Hey Oracle" })'
    ),
    "MessageCard": (
        'C.message({ headline="Text", primary="Priya",'
        ' detail="Running 10 late, start without me." })'
    ),
    "UpcomingCard": (
        'C.upcoming({ headline="in 5 min", primary="Standup",'
        ' detail="Room 4B", minutes=5 })'
    ),
    "HereCard": (
        'C.here_reminder({ primary="Your umbrella", detail="by the door" })'
    ),
    "PersonDossierCard": (
        'C.person_dossier({ person="Marcus", headline="last spoke 2 days ago",'
        ' detail="about the lease, the move", footer="you owe him a reply" })'
    ),
    "SpokenCaptionCard": (
        'C.spoken_caption({ speaker="Jordan",'
        ' primary="Can you send the invoice today?" })'
    ),
    "MorningBriefCard": (
        'C.morning_brief({ primary="Three meetings, rain at noon.",'
        ' bullets={"Standup 9:00", "Dentist 2:30", "Call Mom"} })'
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
    a = list(h.display.last_frame().getdata())
    for t in range(2600, 3600, 50):
        _tick(h, t)
    b = list(h.display.last_frame().getdata())
    diff = sum(1 for x, y in zip(a, b) if x != y)
    assert diff == 0, f"{ctype}: {diff} pixels moved under reduce_motion"


def test_listening_pulse_breathes_under_motion():
    h = _session(reduce=False)
    _show(h, CARDS["ListeningCard"], at=1000)
    _tick(h, 2000)
    a = list(h.display.last_frame().convert("RGB").crop((90, 66, 166, 142)).getdata())
    _tick(h, 2350)
    b = list(h.display.last_frame().convert("RGB").crop((90, 66, 166, 142)).getdata())
    assert a != b, "the listening wake ring did not breathe on hold"


# ---------------------------------------------------------------------------
# Structural safety net: an unmapped card type must never render pure black.
# ---------------------------------------------------------------------------

def test_unknown_card_type_is_not_a_black_frame():
    h = _session(reduce=False)
    # a type with NO draw fn and NO layout — the worst case
    h.execute('__now = 1000; _r.show_card({ type="TotallyUnknownCard",'
              ' primary="Something happened", detail="from a future feature" })')
    _tick(h, 2000)
    assert h.display.bright_pixel_count() > 400, "unmapped card rendered black"


def test_unknown_card_with_layout_uses_layout_renderer():
    h = _session(reduce=False)
    h.execute('__now = 1000; _r.show_card({ type="FutureCard",'
              ' primary="Hello", layout = { primary = {x=128, y=120,'
              ' size="md", color=0xECF0F1} } })')
    _tick(h, 2000)
    assert h.display.bright_pixel_count() > 400


# ---------------------------------------------------------------------------
# The REAL pipeline: HOST-built payloads reach pixels over the BLE path.
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


BLE_CASES = [
    ("message_notification", dict(who="Priya", text="Running late", channel="imessage")),
    ("here_reminder", dict(subject="Your umbrella", place="by the door")),
    ("upcoming_event", dict(title="Standup", minutes=5, place="Room 4B")),
    ("person_dossier", {"data": dict(person="Marcus", last_seen_ago="2 days ago",
                                     topics=["lease", "move"],
                                     last_line="you owe him a reply")}),
    ("spoken_caption", dict(speaker="Jordan", text="Send the invoice today?")),
    ("morning_brief", dict(text="Three meetings, rain at noon.",
                           bullets=["Standup", "Dentist", "Call Mom"])),
    ("listening", dict(source="voice")),
]


@pytest.mark.parametrize("fn,kwargs", BLE_CASES, ids=[c[0] for c in BLE_CASES])
def test_ble_host_payload_reaches_pixels(fn, kwargs):
    from dreamlayer.hud import cards as host_cards
    payload = getattr(host_cards, fn)(**kwargs)
    h = _session(reduce=False)
    h.execute(f"__now = 1000; _r.show_card({_lua_literal(payload)})")
    _tick(h, 2000)
    # not a black disc, and the content band is lit
    assert h.display.bright_pixel_count() > 900, f"{fn}: black/near-black"
    band = h.display.last_frame().convert("L").crop((30, 90, 226, 210))
    assert sum(1 for px in band.getdata() if px >= 12) > 150, f"{fn}: empty body"
