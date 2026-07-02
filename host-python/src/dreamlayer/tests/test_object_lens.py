"""test_object_lens.py — the Object Lens: recognise a thing, panel it."""
from __future__ import annotations

import numpy as np
import pytest

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.object_lens import (
    ObjectLens, ObjectRecognizer, ObjectSighting,
    ProviderRegistry, MemoryProvider, NoteProvider,
    LaptopProvider, CarProvider, PlantProvider,
)

NOW = 1_000_000.0


def frame(v=0.6):
    # a frame with contrast so the mock recognises something
    a = np.full((16, 16), v, dtype=np.float32)
    a[::2] += 0.15
    return a


def says(label, conf=0.9, **attrs):
    return lambda _frame: (label, conf, attrs)


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------

class TestRecognizer:
    def test_none_frame_recognises_nothing(self):
        assert ObjectRecognizer().recognize(None) is None

    def test_blank_frame_recognises_nothing(self):
        blank = np.zeros((16, 16), dtype=np.float32)
        assert ObjectRecognizer().recognize(blank) is None

    def test_mock_is_deterministic(self):
        r = ObjectRecognizer()
        a, b = r.recognize(frame(0.6)), r.recognize(frame(0.6))
        assert a is not None and a.label == b.label

    def test_low_confidence_is_dropped(self):
        r = ObjectRecognizer(classify_fn=says("mug", conf=0.2))
        assert r.recognize(frame()) is None

    def test_a_person_is_never_an_object(self):
        r = ObjectRecognizer(classify_fn=says("person", conf=0.99))
        assert r.recognize(frame()) is None       # deferred to Social Lens

    def test_pluggable_classifier_and_attributes(self):
        r = ObjectRecognizer(classify_fn=says("mug", brand="blue"))
        s = r.recognize(frame())
        assert s.label == "mug" and s.attributes["brand"] == "blue"


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class TestMemoryProvider:
    def _ring(self, *mems):
        ring = SemanticRingBuffer(capacity=64)
        for summary, meta in mems:
            ring.append(MemoryEvent(kind="object", summary=summary,
                                    confidence=0.8, meta=meta), ts=NOW)
        return ring

    def test_recalls_prior_sightings_and_place(self):
        ring = self._ring(
            ("laptop at the desk", {"object": "laptop", "place": "the desk"}),
            ("laptop in the bag", {"object": "laptop", "place": "the bag"}))
        rows = MemoryProvider(ring).build(ObjectSighting("laptop", 0.9))
        assert any("seen before" in r.label for r in rows)
        assert any("2×" in r.detail for r in rows)

    def test_ownership_is_flagged(self):
        ring = self._ring(("bought this book last week",
                           {"object": "book", "owned": True}))
        rows = MemoryProvider(ring).build(ObjectSighting("book", 0.9))
        assert any("already own" in r.label for r in rows)

    def test_private_sightings_never_surface(self):
        ring = self._ring(("laptop at the clinic",
                           {"object": "laptop", "private": True}))
        rows = MemoryProvider(ring).build(ObjectSighting("laptop", 0.9))
        assert rows == []


class TestNoteProvider:
    def test_notes_anchored_to_an_object(self):
        prov = NoteProvider({"mug": ["return this to Sam"]})
        assert prov.matches(ObjectSighting("mug", 0.9))
        rows = prov.build(ObjectSighting("mug", 0.9))
        assert rows[0].detail == "return this to Sam"

    def test_no_notes_no_match(self):
        assert NoteProvider({}).matches(ObjectSighting("mug", 0.9)) is False


class TestIntegrationSeams:
    def test_laptop_recent_files(self):
        prov = LaptopProvider(lambda: {"recent_files": ["notes.md", "budget.xlsx"],
                                       "battery": 82})
        rows = prov.build(ObjectSighting("laptop", 0.9))
        assert any(r.detail == "notes.md" for r in rows)
        assert any(r.value == "82%" for r in rows)

    def test_car_tire_pressure(self):
        rows = CarProvider(lambda: {"tire_pressure": 34, "fuel": 60}).build(
            ObjectSighting("car", 0.9))
        assert any(r.value == "34 psi" for r in rows)

    def test_plant_watering(self):
        rows = PlantProvider(lambda: {"needs_water": True}).build(
            ObjectSighting("houseplant", 0.9))
        assert any(r.label == "needs water" for r in rows)

    def test_seam_only_matches_its_objects(self):
        assert LaptopProvider(lambda: {}).matches(ObjectSighting("mug", 0.9)) is False

    def test_broken_source_is_swallowed(self):
        def boom():
            raise RuntimeError("no dongle")
        rows = CarProvider(boom).build(ObjectSighting("car", 0.9))
        assert rows == []


# ---------------------------------------------------------------------------
# Registry + Lens end to end
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_merges_matching_providers(self):
        reg = ProviderRegistry([
            NoteProvider({"laptop": ["backup tonight"]}),
            LaptopProvider(lambda: {"battery": 50}),
        ])
        panel = reg.build_panel(ObjectSighting("laptop", 0.9))
        assert set(panel.sources) == {"note", "laptop"}
        assert len(panel.rows) == 2


class TestObjectLens:
    def test_look_builds_a_panel(self):
        ring = SemanticRingBuffer(capacity=16)
        lens = ObjectLens(ring=ring, recognizer=ObjectRecognizer(
            classify_fn=says("mug", brand="blue")))
        panel = lens.look(frame())
        assert panel is not None and panel.title == "mug"
        assert panel.subtitle == "blue"
        assert panel.to_hud_card()["type"] == "ObjectPanelCard"

    def test_look_is_veil_gated(self):
        class Paused:
            def allow_capture(self): return False
        lens = ObjectLens(recognizer=ObjectRecognizer(classify_fn=says("mug")),
                          privacy=Paused())
        assert lens.look(frame()) is None

    def test_person_yields_no_panel(self):
        lens = ObjectLens(recognizer=ObjectRecognizer(classify_fn=says("person")))
        assert lens.look(frame()) is None

    def test_orchestrator_wiring(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        orc = Orchestrator(FakeBridge())
        orc.object_lens.recognizer = ObjectRecognizer(classify_fn=says("mug"))
        panel = orc.look_at_object(frame())
        assert panel is not None and panel.title == "mug"
        assert any(f.get("t") == "card" for f in orc.bridge.raw)
        orc.privacy.pause()
        assert orc.look_at_object(frame()) is None
