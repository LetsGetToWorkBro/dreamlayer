"""test_perception.py — Tier 0: the on-glass perception seam.

Pins the heuristic (no model, works offline), the NPU seam (a Vela/ONNX model
plugs into infer_fn and its output maps to typed percepts), the router's
prefer-NPU-fall-back-to-heuristic behaviour, and the end-to-end path where the
Glance Arbiter's coarse read draws from perception.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.ai_brain.perception import (
    PerceptSignals, AudioPercept, HeuristicPerceptor, NpuPerceptor,
    PerceptionRouter, text_density,
)
from dreamlayer.ai_brain import Perceptor
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def flat():
    return np.zeros((16, 16), dtype=np.float32)


def edgy():
    a = np.zeros((16, 16), dtype=np.float32)
    a[:, ::2] = 1.0                    # vertical stripes: high gradient = dense
    return a


# -- cheap image stats: honest, model-free ------------------------------------

def test_text_density_separates_flat_from_edgy():
    assert text_density(flat()) == 0.0
    assert text_density(edgy()) > 0.4
    assert 0.0 <= text_density(edgy()) <= 1.0


# -- the heuristic tier: only what stats can honestly give --------------------

def test_heuristic_reads_density_and_never_fakes_a_face():
    s = HeuristicPerceptor().perceive(edgy())
    assert s.text_density and s.text_density > 0.4
    assert s.has_face is None             # a heuristic can't see a face
    assert s.form_fields is None
    assert "has_face" not in s.as_signals()   # absent, not a false negative


def test_heuristic_merges_device_hints():
    h = HeuristicPerceptor(hint_fn=lambda f: {"has_face": True, "form_fields": 3})
    s = h.perceive(flat())
    assert s.has_face is True and s.form_fields == 3
    assert s.as_signals()["has_face"] is True


def test_heuristic_never_wakes_on_its_own():
    assert HeuristicPerceptor().listen(b"\x00\x00").woke() is False


# -- the NPU tier: a model plugs into the seam --------------------------------

def test_npu_maps_model_output_to_typed_signals():
    def vision(frame):
        return {"has_face": 1, "text_density": 0.72, "form_fields": 4,
                "question": 0, "language": "fr"}
    s = NpuPerceptor(vision_fn=vision).perceive(flat())
    assert s.has_face is True and s.form_fields == 4
    assert s.text_density == 0.72 and s.language == "fr"
    assert s.question is False and s.tier == "npu"


def test_npu_without_a_model_returns_none_to_defer():
    assert NpuPerceptor().perceive(flat()) is None
    assert NpuPerceptor().listen(b"") is None


def test_npu_audio_wake():
    p = NpuPerceptor(audio_fn=lambda a: {"wake": 0.9, "speaking": True, "keyword": "save"})
    a = p.listen(b"pcm")
    assert a.woke() and a.speaking and a.keyword == "save"


def test_npu_satisfies_the_protocol():
    assert isinstance(NpuPerceptor(), Perceptor)
    assert isinstance(HeuristicPerceptor(), Perceptor)


# -- the router: prefer the NPU, fall back, never fail ------------------------

def test_router_prefers_the_npu_when_present():
    r = PerceptionRouter()                          # seeded with heuristic
    assert not r.has_npu()
    r.add_perceptor(NpuPerceptor(vision_fn=lambda f: {"has_face": True}))
    assert r.has_npu()
    assert r.perceive(flat()).tier == "npu"


def test_router_falls_back_when_the_npu_defers():
    r = PerceptionRouter()
    r.add_perceptor(NpuPerceptor(vision_fn=lambda f: None))   # model declines
    s = r.perceive(edgy())
    assert s.tier == "heuristic" and s.text_density > 0.4     # heuristic answered


def test_router_survives_a_throwing_tier():
    class Boom:
        tier, is_npu = "boom", True
        def perceive(self, f): raise RuntimeError("npu crash")
        def listen(self, a): raise RuntimeError("npu crash")
    r = PerceptionRouter()
    r.add_perceptor(Boom())
    assert r.perceive(edgy()).tier == "heuristic"   # crash skipped, not fatal
    assert isinstance(r.listen(b""), AudioPercept)


# -- end to end: the Glance Arbiter's coarse read draws from perception -------

def test_orchestrator_glance_uses_perception_signals():
    br = FakeBridge()
    orc = Orchestrator(br)
    # a wired NPU that reports a form → the arbiter fires the form lens, with no
    # explicit _glance_signals_fn and no fine vision call.
    orc.perception.add_perceptor(NpuPerceptor(vision_fn=lambda f: {"form_fields": 4}))

    class A:
        text = "SUMMARY: a W-9.\nFIELD: Name — your legal name."
        tier = "npu"
        def is_empty(self): return False
    orc.brain.explain = lambda f, p, want="quick": A()
    d = orc.glance(flat())
    assert d.kind == "fire" and d.winner.lens == "scholar_form"


def test_explicit_device_seam_still_wins_over_perception():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc._glance_signals_fn = lambda f: {"has_face": True}   # app-supplied cue
    r = orc._classify_glance(flat())
    assert r.scene == "person"
