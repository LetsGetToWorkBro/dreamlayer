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

    def test_steady_seven_tap_run_still_wakes_the_lens(self):
        # refute 2026-07-20: the old absolute 3.5s window pruned a steadily-paced
        # seven-tap run down to three and MISFIRED her colours. A burst is now any
        # run of taps each within the debounce, however long it takes overall.
        b = FakeBridge()
        hl, clock = _layer(b)
        for i in range(7):
            clock["t"] = i * 1.2                    # 1.2s gaps (< 1.3 debounce), 7.2s span
            hl.tap()
        FakeTimer.fire_last()
        assert not b.cards, "a steady seven-tap run misfired her colours"
        assert b.raw and b.raw[0]["t"] == "prism" and b.raw[0]["active"] == 1

    def test_prism_folds_before_her_colours_open(self):
        # refute 2026-07-20: prism + colours shared ONE hold timer, so opening
        # colours mid-prism-hold cancelled prism's active=0 — and the on-glass
        # lens has no auto-close, so it stuck forever. A new egg now folds the
        # old one back first.
        b = FakeBridge()
        hl, clock = _layer(b)
        for i in range(7):
            clock["t"] = i * 0.3
            hl.tap()
        FakeTimer.fire_last()                       # prism wakes (active=1), holds
        assert b.raw[-1]["active"] == 1
        for i in range(3):
            clock["t"] = 5.0 + i * 0.3              # colours, mid-prism-hold
            hl.tap()
        FakeTimer.fire_last()
        assert any(f.get("active") == 0 for f in b.raw), "prism never folded — stuck on glass"
        assert b.cards[-1][0]["type"] == "JunoColorsCard"

    def test_prism_is_gated_in_dream_mode(self):
        # refute 2026-07-20: only the 3-tap branch checked Dream Mode; the 7-tap
        # prism branch was ungated, so a bond-less Dream session woke the lens.
        b = FakeBridge()
        hl, clock = _layer(b, dream=True)
        for i in range(7):
            clock["t"] = i * 0.3
            hl.tap()
        FakeTimer.fire_last()
        assert not b.raw and not b.cards, "prism fired inside Dream Mode"

    def test_stop_cancels_pending_timers(self):
        b = FakeBridge()
        hl, clock = _layer(b)
        for i in range(3):
            clock["t"] = i * 0.3
            hl.tap()
        hl.stop()
        assert not [t for t in FakeTimer.instances if not t.cancelled], \
            "stop() left a timer armed to fire into a dead session"


class TestSpriteLockstep:
    def _rows(self, text, opener):
        block = text.split(opener, 1)[1]
        rows = re.findall(r'"([.1-7]{32})"', block[:4000])
        return rows[:32]

    def test_juno_color_rows_identical_in_all_three_renderers(self):
        lua = (REPO / "halo-lua/display/renderer.lua").read_text(encoding="utf-8")
        py = (REPO / "host-python/src/dreamlayer/hud/renderer.py").read_text(encoding="utf-8")
        js = (REPO / "landing/assets/sim/halo-sim.js").read_text(encoding="utf-8")
        r_lua = self._rows(lua, "local JUNO_COLOR_ROWS = {")
        r_py = self._rows(py, "_JUNO_COLOR_ROWS = (")
        r_js = self._rows(js, "var JUNO_COLOR_ROWS = [")
        assert len(r_lua) == 32
        assert r_lua == r_py == r_js

    def test_juno_color_palette_identical_in_all_three_renderers(self):
        lua = (REPO / "halo-lua/display/renderer.lua").read_text(encoding="utf-8")
        py = (REPO / "host-python/src/dreamlayer/hud/renderer.py").read_text(encoding="utf-8")
        js = (REPO / "landing/assets/sim/halo-sim.js").read_text(encoding="utf-8")
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
