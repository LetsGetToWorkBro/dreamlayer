"""Every card type the Brain can build draws properly on the phone.

`hud/cards.py` builds 40 card types. halo-lua drew 45. The Live Lens drew 30 —
so fifteen types fell through to `glassEventCard`, which draws `eyebrow` and
`primary` AND NOTHING ELSE. A card whose answer lives in another field arrived
gutted: Ember without its cue or rep count, Scholar and Taste without their
item lists, the glance chooser without the options that are the entire
question, a message without which inbox it came from, an event without its
countdown.

Fourteen of the fifteen already drew properly on the GLASSES, which made the
phone the surface that was behind — the opposite of what the pre-hardware
framing suggests.

This file exists to keep that closed. The generic fallback is the failure mode
it guards: `glassEventCard` will happily make a missing renderer look like a
present one, which is how a checker starts agreeing with itself.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
CARDS = ROOT / "host-python" / "src" / "dreamlayer" / "hud" / "cards.py"

#: The one type the DEVICE deliberately does not draw. It receives palette
#: weather natively as a raw `palette` frame (`ble/message_types.lua` PALETTE →
#: `display/palette_animator.lua`), which animates the whole disc rather than
#: drawing a card about it. The phone has no such channel, so the card is the
#: phone's palette surface. An asymmetry in TRANSPORT, not a missing drawing.
DEVICE_NATIVE_ONLY = {"PaletteShiftCard"}

#: Empty, and it stayed empty by BUILDING the missing producer rather than by
#: excusing the gap. `palette_shift_card` had no caller anywhere in the tree for
#: as long as it existed; `dream_reactors.note_mic` calls it now, from the same
#: `MicReactor` primitive the glasses' own engine runs.
NO_PRODUCER: set = set()


def _hud():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hud_reach", ROOT / "scripts" / "hud_reachability.py")
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def surfaces():
    h = _hud()
    return h._drawn_on_glass(), h._drawn_on_live_lens()


@pytest.fixture(scope="module")
def built():
    return set(re.findall(r'"type":\s*"([A-Za-z]+Card)"',
                          CARDS.read_text(encoding="utf-8")))


class TestThePhoneDrawsEverythingItIsSent:
    def test_every_built_card_type_has_a_live_lens_renderer(self, built,
                                                            surfaces):
        _device, live = surfaces
        missing = sorted(built - live - NO_PRODUCER)
        assert not missing, (
            f"{len(missing)} card type(s) fall through to glassEventCard, which "
            f"draws eyebrow+primary and drops the field carrying the answer: "
            f"{missing}")

    def test_the_count_did_not_quietly_shrink(self, surfaces):
        _device, live = surfaces
        assert len(live) >= 45, (
            f"the Live Lens draws {len(live)} types, down from 45 — a renderer "
            "was removed or the dispatch scan stopped matching")

    def test_the_two_surfaces_are_level(self, surfaces):
        device, live = surfaces
        # Not equality of the SETS — each surface legitimately draws types the
        # other never receives — but neither may fall behind on what the Brain
        # actually builds. The one deliberate exception is pinned by name.
        assert len(live) >= len(device) - len(DEVICE_NATIVE_ONLY | NO_PRODUCER)


class TestTheDeviceIsStillAhead:
    def test_every_built_type_draws_on_the_device_except_the_native_one(
            self, built, surfaces):
        device, _live = surfaces
        assert sorted(built - device) == sorted(DEVICE_NATIVE_ONLY)

    def test_the_native_exception_is_a_transport_difference(self):
        """`PaletteShiftCard` has no halo-lua drawing ON PURPOSE.

        The device gets palette weather as a raw frame the animator consumes;
        drawing a card about it would be a second, worse channel for something
        the glasses already do natively. Asserted against the protocol rather
        than against a comment, so the claim rots loudly if PALETTE is removed.
        """
        proto = (ROOT / "halo-lua" / "ble" / "message_types.lua").read_text(
            encoding="utf-8")
        assert "PALETTE" in proto
        from dreamlayer.bridge.base import RAW_FRAME_TYPES
        assert "palette" in RAW_FRAME_TYPES


class TestTheNewRenderersKeepTheirContent:
    """The point of a bespoke renderer is the field the generic one drops.
    Each case names that field, so a renderer that regresses to
    eyebrow+primary fails here rather than looking fine."""

    @pytest.fixture(scope="class")
    @classmethod
    def page(cls):
        from dreamlayer.ai_brain.server import live
        return live._PAGE

    @pytest.mark.parametrize("fn,field", [
        ("glassEmberCard", "c.cue"),               # the thing being practised
        ("glassEmberCard", "c.answer"),            # the whole point of a reveal
        ("glassEmberCard", "c.reps"),              # the count you feel
        ("glassListCard", "c.items"),              # Scholar/Taste ARE the list
        ("glassListCard", "c.unavailable"),        # could not look != nothing
        ("glassGlanceChoiceCard", "c.options"),    # a question needs answers
        ("glassMessageCard", "c.channel"),         # which inbox
        ("glassMessageCard", "c.headline"),        # who from
        ("glassUpcomingCard", "c.minutes"),        # the countdown
        ("glassHereCard", "c.detail"),
        ("glassLowConfidenceCard", "c.kind"),
        ("glassPaletteShiftCard", "c.colors"),     # not text at all
    ])
    def test_the_renderer_reads_the_field_that_matters(self, page, fn, field):
        start = page.index("function " + fn + "(")
        end = page.index("\nfunction ", start + 10)
        assert field in page[start:end], (
            f"{fn} no longer reads {field} — the field the generic renderer "
            "drops is exactly the one this renderer exists to keep")

    @pytest.mark.parametrize("ctype,fn", [
        ("EmberPromptCard", "glassEmberCard"),
        ("EmberFlareCard", "glassEmberCard"),
        ("EmberRevealCard", "glassEmberCard"),
        ("EmberGraduatedCard", "glassEmberCard"),
        ("ScholarCard", "glassListCard"),
        ("TasteCard", "glassListCard"),
        ("GlanceChoiceCard", "glassGlanceChoiceCard"),
        ("MessageCard", "glassMessageCard"),
        ("UpcomingCard", "glassUpcomingCard"),
        ("HereCard", "glassHereCard"),
        ("QueryListeningCard", "glassQueryListeningCard"),
        ("LoadingCard", "glassLoadingCard"),
        ("LowConfidenceCard", "glassLowConfidenceCard"),
        ("ErrorCard", "glassErrorCard"),
        ("PaletteShiftCard", "glassPaletteShiftCard"),
    ])
    def test_the_dispatch_routes_it(self, page, ctype, fn):
        # A renderer nothing dispatches to is a renderer that never runs.
        assert re.search(r't === "%s"[^;]*%s\(c\)' % (ctype, fn), page), (
            f"{ctype} is not routed to {fn} in renderEvent")

    def test_the_generic_fallback_is_still_last(self, page):
        # It must stay — a future card type has to show SOMETHING — but it must
        # stay the final else, never a branch that shadows a real renderer.
        assert "else glassEventCard(c);" in page


class TestTheAnimatedOnesCleanUp:
    """`QueryListeningCard` and `LoadingCard` carry `{type, dismiss_ms}` and
    nothing else — they are purely states, so the drawing IS the content.
    Both animate, and an animation that outlives its card paints over the next
    one."""

    @pytest.fixture(scope="class")
    @classmethod
    def page(cls):
        from dreamlayer.ai_brain.server import live
        return live._PAGE

    @pytest.mark.parametrize("fn", ["glassQueryListeningCard",
                                    "glassLoadingCard"])
    def test_it_clears_the_previous_animation(self, page, fn):
        start = page.index("function " + fn + "(")
        end = page.index("\nfunction ", start + 10)
        body = page[start:end]
        assert "clearInterval(glassAnim)" in body, (
            f"{fn} starts an interval without clearing the previous one — two "
            "animations would fight over the same canvas")
        assert "glassAnim = setInterval" in body

    def test_glass_clear_stops_animations(self, page):
        # The other half: whatever is running must die when the card does.
        start = page.index("function glassClear(")
        end = page.index("\nfunction ", start + 10)
        assert "clearInterval(glassAnim)" in page[start:end]
