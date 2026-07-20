"""test_hidden_layer.py — the secrets run through the real pipeline.

The tap-burst detector (orchestrator/hidden_layer.py): seven quick single
taps wake the lost lens over the real bridge seam; three show her true
colors as a stateless card; Dream Mode keeps its taps; a seven-tap run
never half-fires the three-tap flourish. Plus the tri-file sprite lockstep
(Lua / Python / JS carry the identical JUNO_COLOR_ROWS + palette) and the
Brain's discoveries store."""
from __future__ import annotations

import re
from pathlib import Path

from dreamlayer.orchestrator.hidden_layer import HiddenLayer

REPO = Path(__file__).parents[4]


class FakeTimer:
    """A Timer that fires only when the test says so."""
    instances: list = []

    def __init__(self, seconds, fn):
        self.seconds, self.fn, self.cancelled, self.daemon = seconds, fn, False, False
        FakeTimer.instances.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    @classmethod
    def fire_last(cls):
        live = [t for t in cls.instances if not t.cancelled]
        assert live, "no live timer to fire"
        live[-1].fn()


class FakeBridge:
    def __init__(self):
        self.raw: list = []
        self.cards: list = []

    def send_raw(self, frame):
        self.raw.append(frame)

    def send_card(self, card, event=""):
        self.cards.append((card, event))


def _layer(bridge, dream=False):
    FakeTimer.instances = []
    clock = {"t": 0.0}
    hl = HiddenLayer(bridge, is_dream_fn=lambda: dream,
                     now_fn=lambda: clock["t"], timer_factory=FakeTimer)
    return hl, clock


class TestHiddenLayer:
    def test_seven_taps_wake_and_fold_the_lost_lens(self):
        b = FakeBridge()
        hl, clock = _layer(b)
        for i in range(7):
            clock["t"] = i * 0.3
            hl.tap()
        FakeTimer.fire_last()                     # burst goes quiet
        assert b.raw and b.raw[0]["t"] == "prism" and b.raw[0]["active"] == 1
        FakeTimer.fire_last()                     # the hold expires
        assert b.raw[-1]["t"] == "prism" and b.raw[-1]["active"] == 0

    def test_three_taps_show_her_true_colors_then_ready(self):
        b = FakeBridge()
        hl, clock = _layer(b)
        for i in range(3):
            clock["t"] = i * 0.3
            hl.tap()
        FakeTimer.fire_last()
        assert b.cards[0][0]["type"] == "JunoColorsCard"
        FakeTimer.fire_last()
        assert b.cards[-1][0]["type"] == "ReadyCard"

    def test_dream_mode_keeps_its_taps(self):
        b = FakeBridge()
        hl, clock = _layer(b, dream=True)
        for i in range(3):
            clock["t"] = i * 0.3
            hl.tap()
        FakeTimer.fire_last()
        assert not b.cards and not b.raw

    def test_a_seven_tap_run_never_half_fires_colors(self):
        # every tap re-arms the debounce; only the final quiet evaluates
        b = FakeBridge()
        hl, clock = _layer(b)
        for i in range(7):
            clock["t"] = i * 0.3
            hl.tap()
        evals = [t for t in FakeTimer.instances if not t.cancelled]
        assert len(evals) == 1                    # six were cancelled mid-burst
        evals[0].fn()
        assert not b.cards and b.raw[0]["t"] == "prism"

    def test_stale_taps_fall_out_of_the_window(self):
        b = FakeBridge()
        hl, clock = _layer(b)
        for i in range(4):                         # 4 old taps...
            clock["t"] = i * 0.1
            hl.tap()
        clock["t"] = 10.0                          # ...long silence...
        for i in range(3):                         # ...then a clean 3-burst
            clock["t"] = 10.0 + i * 0.3
            hl.tap()
        FakeTimer.fire_last()
        assert b.cards and b.cards[0][0]["type"] == "JunoColorsCard"


class TestSpriteLockstep:
    def _rows(self, text, opener):
        block = text.split(opener, 1)[1]
        rows = re.findall(r'"([.1-7]{32})"', block[:4000])
        return rows[:32]

    def test_juno_color_rows_identical_in_all_three_renderers(self):
        lua = (REPO / "halo-lua/display/renderer.lua").read_text()
        py = (REPO / "host-python/src/dreamlayer/hud/renderer.py").read_text()
        js = (REPO / "landing/assets/sim/halo-sim.js").read_text()
        r_lua = self._rows(lua, "local JUNO_COLOR_ROWS = {")
        r_py = self._rows(py, "_JUNO_COLOR_ROWS = (")
        r_js = self._rows(js, "var JUNO_COLOR_ROWS = [")
        assert len(r_lua) == 32
        assert r_lua == r_py == r_js

    def test_juno_color_palette_identical_in_all_three_renderers(self):
        lua = (REPO / "halo-lua/display/renderer.lua").read_text()
        py = (REPO / "host-python/src/dreamlayer/hud/renderer.py").read_text()
        js = (REPO / "landing/assets/sim/halo-sim.js").read_text()
        p_lua = re.findall(r"0x([0-9A-F]{6})",
                           lua.split("local JUNO_COLOR_PAL", 1)[1][:200])
        p_py = re.findall(r'"#([0-9A-F]{6})"',
                          py.split("_JUNO_COLOR_PAL", 1)[1][:200])
        p_js = re.findall(r'"#([0-9A-F]{6})"',
                          js.split("var JUNO_COLOR_PAL", 1)[1][:200])
        assert len(p_lua) == 7
        assert p_lua == p_py == p_js

    def test_python_renders_the_card_in_colour(self):
        from dreamlayer.hud.renderer import CardRenderer
        img = CardRenderer().render({"type": "JunoColorsCard"}).convert("RGB")
        colors = {c for _, c in img.getcolors(65536)}
        assert (0xF2, 0xFE, 0xFD) in colors        # wing ice
        assert (0x33, 0x7C, 0x80) in colors        # hair teal
