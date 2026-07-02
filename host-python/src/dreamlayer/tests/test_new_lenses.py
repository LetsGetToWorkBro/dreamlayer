"""test_new_lenses.py — Label, Waypath, and Rosetta."""
from __future__ import annotations

import numpy as np

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.object_lens import (
    ObjectLens, ObjectRecognizer, ProviderRegistry, ObjectSighting,
    LabelProvider, ShoppingProvider, DietaryProfile, RosettaProvider,
)
from dreamlayer.orchestrator.waypath import (
    WaypathLens, relative_direction,
)
from dreamlayer.rosetta import RosettaLens, detect_language

NOW = 1000.0


def frame():
    a = np.full((16, 16), 0.6, dtype=np.float32)
    a[::2] += 0.15
    return a


def says(label, **attrs):
    return ObjectRecognizer(classify_fn=lambda _f: (label, 0.9, attrs))


# ---------------------------------------------------------------------------
# Label Lens
# ---------------------------------------------------------------------------

class TestLabel:
    def test_dietary_avoidance_flags_a_match(self):
        prof = DietaryProfile(avoid={"dairy"})
        rows = LabelProvider(prof).build(
            ObjectSighting("milk chocolate bar", 0.9,
                           {"ingredients": "sugar, milk, cocoa"}))
        assert any(r.detail == "dairy" for r in rows)

    def test_no_flag_when_clean(self):
        prof = DietaryProfile(avoid={"peanut"})
        rows = LabelProvider(prof).build(
            ObjectSighting("apple", 0.9, {"ingredients": "apple"}))
        assert rows == []

    def test_returned_before_from_memory(self):
        ring = SemanticRingBuffer(capacity=16)
        ring.append(MemoryEvent(kind="object", summary="returned the acme kettle",
                                confidence=0.8,
                                meta={"object": "kettle", "returned": True}),
                    ts=NOW)
        rows = LabelProvider(DietaryProfile(), ring).build(
            ObjectSighting("kettle", 0.9))
        assert any("returned" in r.label for r in rows)

    def test_shopping_provider_is_the_cloud_seam(self):
        prov = ShoppingProvider(lambda label, attrs: {
            "cheaper": "$18 at Corner Store", "rating": 4.2})
        rows = prov.build(ObjectSighting("kettle", 0.9))
        assert any(r.label == "cheaper nearby" for r in rows)
        assert any(r.value == "4.2" for r in rows)

    def test_label_through_the_object_lens(self):
        lens = ObjectLens(
            recognizer=says("almond milk", ingredients="almond, water"),
            registry=ProviderRegistry([LabelProvider(DietaryProfile(avoid={"nuts"}))]))
        panel = lens.look(frame())
        assert any(r.detail == "nuts" for r in panel.rows)


# ---------------------------------------------------------------------------
# Waypath Lens
# ---------------------------------------------------------------------------

class TestWaypath:
    def test_relative_directions(self):
        assert relative_direction(0) == "ahead"
        assert relative_direction(90) == "to your right"
        assert relative_direction(180) == "behind you"
        assert relative_direction(270) == "to your left"

    def test_locate_uses_heading(self):
        wp = WaypathLens()
        wp.remember("keys", bearing_deg=90, distance_m=12, place="the desk")
        # facing north: keys are to the right
        cue = wp.locate("keys", heading_deg=0)
        assert cue.found and cue.direction == "to your right"
        assert cue.text == "12m to your right"
        # turn to face east (90): the keys are now straight ahead
        assert wp.locate("keys", heading_deg=90).direction == "ahead"

    def test_fuzzy_match_and_missing(self):
        wp = WaypathLens()
        wp.remember("my car", bearing_deg=200, distance_m=30)
        assert wp.locate("car").found                      # substring match
        assert not wp.locate("umbrella").found             # never saved

    def test_card_only_when_found(self):
        wp = WaypathLens()
        assert wp.to_hud_card(wp.locate("nothing")) is None


# ---------------------------------------------------------------------------
# Rosetta Lens
# ---------------------------------------------------------------------------

class TestRosetta:
    def test_detects_language(self):
        assert detect_language("el gato está en la mesa") == "es"
        assert detect_language("the cat is on the table") == "en"

    def test_no_model_passes_source_through(self):
        res = RosettaLens().read("hola amigo", target="en")
        assert res.source_lang == "es" and res.engine == "none"
        assert not res.changed()

    def test_translates_with_a_model(self):
        r = RosettaLens(translate_fn=lambda t, tgt: "hello friend")
        res = r.read("hola amigo", target="en")
        assert res.translated == "hello friend" and res.changed()

    def test_same_language_is_a_noop(self):
        r = RosettaLens(translate_fn=lambda t, tgt: "SHOULD NOT RUN")
        res = r.read("just english here", target="en")
        assert not res.changed()

    def test_rosetta_provider_translates_seen_text(self):
        r = RosettaLens(translate_fn=lambda t, tgt: "[grilled fish]")
        lens = ObjectLens(
            recognizer=says("menu", text="pescado a la parrilla"),
            registry=ProviderRegistry([RosettaProvider(r)]))
        panel = lens.look(frame())
        assert any("grilled fish" in r_.detail for r_ in panel.rows)


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------

class TestOrchestratorWiring:
    def _orc(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        return Orchestrator(FakeBridge())

    def test_find_way_cards_and_veil(self):
        orc = self._orc()
        orc.waypath.remember("keys", bearing_deg=270, distance_m=5)
        cue = orc.find_way("keys", heading_deg=0)
        assert cue.found and cue.direction == "to your left"
        assert any(f.get("t") == "card" for f in orc.bridge.raw)
        orc.privacy.pause()
        assert orc.find_way("keys") is None

    def test_dietary_and_translate_wired(self):
        orc = self._orc()
        orc.dietary.avoid.add("dairy")
        orc.object_lens.recognizer = says("cheese", ingredients="milk, salt")
        panel = orc.look_at_object(frame())
        assert any(r.detail == "dairy" for r in panel.rows)
        assert orc.translate_seen("hola", target="en").source_lang == "es"
