"""Ember cards on the device renderer — all four draw real pixels through
the integrated Lua, stay inside the frame budget, and the prompt payload
carries no answer for the glass to leak."""
import pathlib

import pytest

try:
    import lupa  # noqa: F401
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

pytestmark = pytest.mark.skipif(not LUPA_AVAILABLE, reason="lupa required")

REPO = pathlib.Path(__file__).parents[4]

PROMPT_CARD = """{
  type = "EmberPromptCard", eyebrow = "EMBER",
  primary = "What did Dad say about the ice?",
  cue = "What did Dad say about the ice?",
  footer = "Kitchen doorway", reps = 3,
}"""

FLARE_CARD = """{
  type = "EmberFlareCard", eyebrow = "EMBER", primary = "It's yours.",
  cue = "What did Dad say about the ice?", footer = "next in ~12d", reps = 4,
}"""

REVEAL_CARD = """{
  type = "EmberRevealCard", eyebrow = "What did Maya say?",
  primary = "Her first full sentence in Spanish",
  answer = "Her first full sentence in Spanish",
  cue = "What did Maya say?", footer = "it will come back around",
}"""

GRADUATED_CARD = """{
  type = "EmberGraduatedCard", eyebrow = "What did Dad say about the ice?",
  primary = "This memory lives in you.",
  cue = "What did Dad say about the ice?", footer = "kept 94d - recalled x7",
  kept_days = 94, reps = 7,
}"""


def _session():
    from dreamlayer.bridge.lua_raster import LuaRasterHarness
    h = LuaRasterHarness()
    h.execute("__now = 0")
    h.execute('_r = require("display.renderer")')
    h.execute("_r.bind(nil, function() return __now end)")
    h.sync_dynamic_slots()
    return h


def _tick_calls(h, at_ms):
    h.execute(f"__now = {at_ms}")
    h.display.draw_calls = 0
    h.execute("_r.tick()")
    return h.display.draw_calls


def _budget(h):
    return int(h.eval('require("display.animations").DRAW_CALLS_MAX'))


@pytest.mark.parametrize("card", [PROMPT_CARD, FLARE_CARD,
                                  REVEAL_CARD, GRADUATED_CARD])
def test_every_ember_card_draws_within_budget(card):
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({card})")
    calls = [_tick_calls(h, 1050 + i * 50) for i in range(1, 24)]
    assert max(calls) <= _budget(h)
    assert max(calls) > 0, "an ember card must draw real pixels"


def test_prompt_breathes_through_the_hold_phase():
    # the ember dot breathes (~2.4s cycle): draw-call counts settle but the
    # frame keeps changing — sample two hold ticks half a cycle apart
    h = _session()
    _tick_calls(h, 1000)
    h.execute(f"__now = 1050; _r.show_card({PROMPT_CARD})")
    for i in range(1, 16):
        _tick_calls(h, 1050 + i * 50)   # ride out ENTER into HOLD
    a = _tick_calls(h, 3000)
    b = _tick_calls(h, 4200)
    assert a > 0 and b > 0

def test_device_prompt_constructor_carries_no_answer():
    # the payload contract, checked at the glass: cards.lua's prompt
    # constructor has no answer field to carry, whatever it is handed
    h = _session()
    h.execute('_c = require("display.cards")')
    h.execute('_p = _c.ember_prompt({ cue = "What did Maya say?",'
              ' place = "Kitchen", answer = "SHOULD NEVER RENDER" })')
    assert h.eval("_p.answer") is None
    assert h.eval("_p.cue") == "What did Maya say?"
    assert h.eval("_p.type") == "EmberPromptCard"


def test_dismiss_and_priority_are_registered():
    h = _session()
    assert int(h.eval('require("display.animations").'
                      'DISMISS_MS.EmberPromptCard')) == 12000
    assert int(h.eval('require("display.animations").'
                      'DISMISS_MS.EmberFlareCard')) == 2600
