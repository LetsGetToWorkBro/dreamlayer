"""Parity: halo-lua/app/figment_stage.lua vs the Python reference Stage.

Requires lupa; skipped headlessly when unavailable.
"""
import json
import random
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

from dreamlayer.reality_compiler.v2 import (   # noqa: E402
    RealityCompilerV2, Stage, lift, transport,
)
from dreamlayer.reality_compiler.schema import SimpleCounterIntent  # noqa: E402

HALO_LUA = Path(__file__).resolve().parents[4] / "halo-lua"

HARNESS = '''
local jsonlib = require("lib.json")
local stage = require("app.figment_stage")
local drawn, sent, handlers = {}, {}, {}
stage.bind({
  display = {
    text  = function(s, x, y, opts)
              drawn[#drawn+1] = {text=s, color=opts and opts.color,
                                 pulse=opts and opts.pulse} end,
    clear = function() drawn = {} end,
    show  = function()
              local copy = {}
              for i, d in ipairs(drawn) do copy[i] = d end
              _G.__shown = copy
            end,
  },
  send    = function(tbl) sent[#sent+1] = tbl end,
  battery = function() return _G.__battery or 100 end,
  random  = function() return 0.5 end,
})
stage.register({ register = function(t, fn) handlers[t] = fn end })
return {
  stage    = stage,
  handlers = handlers,
  decode   = function(s) return jsonlib.decode(s) end,
  shown    = function() return _G.__shown or {} end,
  sent     = function() return sent end,
}
'''


@pytest.fixture
def lua():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{HALO_LUA}/?.lua;" .. package.path')
    return rt.execute(HARNESS)


def deliver(lua, envelope: dict):
    msg = lua["decode"](json.dumps(envelope))
    lua["handlers"][envelope["t"]](msg)


def put_and_swap(lua, fig):
    deliver(lua, transport.put_envelope(fig))
    deliver(lua, transport.swap_envelope(fig.id))


def shown_texts(lua) -> list[str]:
    shown = lua["shown"]()
    return [shown[i + 1]["text"] for i in range(len(shown))]


def rolls_figment():
    rc = RealityCompilerV2()
    s = rc.rehearse("Rolling rounds")
    s.double_tap()
    s.say("rolling - three minutes")
    s.say("last ten seconds, pulse")
    s.say("then it starts again")
    return s.finish().figment


class TestLifecycle:
    def test_put_swap_ack(self, lua):
        fig = rolls_figment()
        put_and_swap(lua, fig)
        assert lua["stage"].active_id() == fig.id
        assert lua["stage"].is_running()
        sent = lua["sent"]()
        assert sent[1]["t"] == "figment_ack" and sent[1]["ok"] is True

    def test_malformed_figment_refused(self, lua):
        deliver(lua, {"t": "figment_put", "id": "evil",
                      "figment": {"initial": "x", "scenes": {}},
                      "hash": "h"})
        sent = lua["sent"]()
        assert sent[1]["ok"] is False
        deliver(lua, {"t": "figment_swap", "id": "evil"})
        assert not lua["stage"].is_running()

    def test_over_budget_pulse_refused_on_device(self, lua):
        # defense in depth: even if the host were bypassed, the stage's
        # own clamps reject a strobing figment at load
        fig = rolls_figment()
        fig.scenes["rolling"].pulse.rate_hz = 30.0
        deliver(lua, transport.put_envelope(fig))
        assert lua["sent"]()[1]["ok"] is False

    def test_revoke_clears_stage(self, lua):
        fig = rolls_figment()
        put_and_swap(lua, fig)
        deliver(lua, transport.revoke_envelope(fig.id))
        assert not lua["stage"].is_running()
        assert lua["stage"].active_id() is None

    def test_hot_swap_replaces_running(self, lua):
        a, b = rolls_figment(), rolls_figment()
        b.name, b.id = "Other", "otherid"
        put_and_swap(lua, a)
        lua["stage"].on_event("double")
        lua["stage"].tick(5.0)
        put_and_swap(lua, b)
        assert lua["stage"].active_id() == "otherid"
        assert lua["stage"].is_running()


class TestParityWithPython:
    def test_countdown_parity(self, lua):
        fig = rolls_figment()
        put_and_swap(lua, fig)
        py = Stage(fig, rng=random.Random(1))

        lua["stage"].on_event("double")
        py.inject("double")
        for _ in range(350):                  # 175 s in 0.5 s device ticks
            lua["stage"].tick(0.5)
        py.step(175.0)

        assert shown_texts(lua) == [ln.text for ln in py.frame().lines]

    def test_counter_parity(self, lua):
        fig = lift(SimpleCounterIntent(start_value=5, increment=2))
        put_and_swap(lua, fig)
        py = Stage(fig)
        for _ in range(3):
            lua["stage"].on_event("single")
            py.inject("single")
        lua["stage"].tick(0.05)
        assert shown_texts(lua) == [ln.text for ln in py.frame().lines]
        assert "11" in shown_texts(lua)

    def test_emit_token_bucket_parity(self, lua):
        fig = lift(SimpleCounterIntent())
        # bind an emit to the tap for the flood test
        fig.scenes["count"].on["single"].emit = "tap"
        put_and_swap(lua, fig)
        py = Stage(fig)
        for _ in range(20):                   # 20 taps in zero time
            lua["stage"].on_event("single")
            py.inject("single")
        sent = lua["sent"]()
        lua_emits = [sent[i + 1] for i in range(len(sent))
                     if sent[i + 1]["t"] == "figment_event"]
        assert len(lua_emits) == len(py.emits) == 5     # burst cap on both

    def test_named_slots_parity(self, lua):
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, Transition, SELF, TextLine,
        )
        fig = Figment(name="rosetta", initial="a")
        a = fig.add_scene(Scene(id="a", lines=[
            TextLine("{slot}", row=0),
            TextLine("{slot:es}", row=1),
            TextLine("{slot:en}", row=2),
        ]))
        a.on["text"] = Transition(target=SELF)
        put_and_swap(lua, fig)
        py = Stage(fig)

        for slot, text in [("", "d"), ("es", "hola"), ("en", "hello")]:
            deliver(lua, transport.text_envelope(fig.id, text, slot))
            py.inject(("text:" + slot) if slot else "text", text)
        lua["stage"].tick(0.05)
        assert shown_texts(lua) == [ln.text for ln in py.frame().lines]
        assert shown_texts(lua) == ["d", "hola", "hello"]

    def test_named_slot_cap_parity(self, lua):
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, Transition, SELF, TextLine,
        )
        from dreamlayer.reality_compiler.v2.figment import MAX_SLOTS
        fig = Figment(name="cap", initial="a")
        a = fig.add_scene(Scene(id="a", lines=[TextLine("{slot:keep}", row=0)]))
        a.on["text"] = Transition(target=SELF)
        put_and_swap(lua, fig)
        # fill 'keep' first, then overflow with new names: 'keep' survives
        deliver(lua, transport.text_envelope(fig.id, "K", "keep"))
        for i in range(MAX_SLOTS + 4):
            deliver(lua, transport.text_envelope(fig.id, "v", "x%d" % i))
        lua["stage"].tick(0.05)
        assert shown_texts(lua) == ["K"]     # known slot never evicted

    def test_rosetta_figment_named_slots_on_glass(self, lua):
        # the migration pilot end-to-end: the Rosetta figment on the real Lua
        # stage, fed three named slots, draws translation + original + langs —
        # no SpokenCaptionCard, no per-card renderer twin
        from dreamlayer.reality_compiler.v2 import native
        fig = native.rosetta_figment()
        put_and_swap(lua, fig)
        py = Stage(fig)
        for slot, val in (("langs", "ES → EN"),
                          ("translation", "hello, thanks"),
                          ("original", "hola, gracias")):
            deliver(lua, transport.text_envelope(fig.id, val, slot))
            py.inject("text:" + slot, val)
        lua["stage"].tick(0.05)
        shown = shown_texts(lua)
        assert shown == [ln.text for ln in py.frame().lines]
        assert "hello, thanks" in shown          # translation, primary line
        assert "hola, gracias" in shown          # original, secondary line
        assert "ES → EN" in shown                # the language pair eyebrow

    def test_morning_brief_figment_on_glass(self, lua):
        # second card off the card path: the morning brief on the real Lua stage,
        # fed named slots, draws the eyebrow + synthesis + points and auto-clears
        from dreamlayer.reality_compiler.v2 import native
        fig = native.morning_brief_figment()
        put_and_swap(lua, fig)
        py = Stage(fig)
        for slot, val in (("synthesis", "A busy day ahead."),
                          ("point1", "Standup 9am"),
                          ("point2", "1 new text")):
            deliver(lua, transport.text_envelope(fig.id, val, slot))
            py.inject("text:" + slot, val)
        lua["stage"].tick(0.05)
        shown = shown_texts(lua)
        assert shown == [ln.text for ln in py.frame().lines]
        assert "YOUR DAY" in shown
        assert "A busy day ahead." in shown
        assert "Standup 9am" in shown and "1 new text" in shown
        # auto-clears after its window (owns the stage, then returns to ambient)
        for _ in range(20):
            lua["stage"].tick(0.5)
        assert not lua["stage"].is_running()

    def test_guarded_loop_parity(self, lua):
        # 3 rounds of 1 s work — both stages end after exactly 3 cycles
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, CounterDecl, CounterOp, Guard, Transition, END,
            SELF, TextLine,
        )
        fig = Figment(name="t", initial="work")
        fig.add_counter(CounterDecl("round", start=1, lo=1, hi=3))
        fig.add_scene(Scene(
            id="work", duration_sec=1.0,
            lines=[TextLine("{count:round}", row=1)],
            on_timeout=[
                Transition(target=END, when=Guard("round", "ge", 3)),
                Transition(target=SELF,
                           counter_ops=[CounterOp("round", "inc", 1)]),
            ]))
        put_and_swap(lua, fig)
        py = Stage(fig)
        for _ in range(10):
            lua["stage"].tick(0.5)
        py.step(5.0)
        assert py.ended
        assert not lua["stage"].is_running()


class TestElapsedParityRegression:
    """A differential-testing find (N3): a self-looping timed scene froze
    {elapsed} at duration+overshoot on the Lua stage but at exactly duration in
    the Python reference. The Lua tick loop now lands on the boundary first."""

    def test_self_loop_frozen_elapsed_matches_reference(self, lua):
        from dreamlayer.reality_compiler.v2 import Figment, Scene, TextLine, \
            Transition, SELF, END
        fig = Figment(name="loop", initial="a")
        a = fig.add_scene(Scene(id="a", duration_sec=2.0,
                                lines=[TextLine("{elapsed}", row=0)],
                                on_timeout=[Transition(target=SELF)]))
        a.on["double"] = Transition(target=END)
        put_and_swap(lua, fig)
        py = Stage(fig)
        for _ in range(10):
            lua["stage"].tick(3.0)     # 3s steps overshoot the 2s scene each time
            py.step(3.0)
        assert shown_texts(lua) == [ln.text for ln in py.frame().lines]
        assert shown_texts(lua) == ["2"]     # frozen at the scene's duration
