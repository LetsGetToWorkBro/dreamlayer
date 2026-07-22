"""The frontier "look closer" lenses (math/doc/depth/find/segment/sky/dream)
lived on the Orchestrator's glance hub, which the shipped Brain never ran — so
they were unreachable from the phone / Live Lens. These tests pin the new live
path: WorldLensHost.look_lens dispatches to the on-device engines, world_look
routes ?lens=… to it, the Veil blinds it, a missing model self-describes with a
`need`, and the caps report honestly (no longer 'dormant').
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer import capabilities as C
from dreamlayer.ai_brain.server import live as live_mod
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.world_lens import build_world_lens


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


class _FakeMath:
    available = True
    def read_math(self, frame):
        return "e^{i\\pi}+1=0"


def test_unknown_lens_is_rejected(brain):
    wl = build_world_lens(brain)
    assert wl.look_lens(object(), "nope")["reason"] == "unknown-lens"


def test_missing_model_self_describes(brain):
    wl = build_world_lens(brain)
    r = wl.look_lens(object(), "math")           # pix2tex not installed in CI
    assert r["ok"] is False and r["need"] == "math_ocr" and r["pack"]


def test_lens_runs_when_model_present(brain):
    wl = build_world_lens(brain)
    wl._extras_cache = {"math": _FakeMath()}
    r = wl.look_lens(object(), "math")
    assert r["ok"] is True and r["latex"] == "e^{i\\pi}+1=0"


def test_veil_blinds_the_lens(brain):
    brain.config.network_mode = "lan_only"       # incognito
    wl = build_world_lens(brain)
    wl._extras_cache = {"math": _FakeMath()}
    r = wl.look_lens(object(), "math")
    assert r["ok"] is False and r["veiled"] is True


def test_world_look_routes_the_lens(brain, monkeypatch):
    # world_look(lens=...) must reach look_lens and return its result verbatim
    fake = {"ok": True, "lens": "math", "latex": "x"}
    monkeypatch.setattr(Brain, "world_lens",
                        lambda self: type("W", (), {"look_lens": lambda s, f, l, a: fake})())
    out = live_mod.world_look(brain, object(), lens="math")
    assert out == fake


def test_ambient_never_uses_a_lens(brain, monkeypatch):
    # an ambient (passive-loop) frame must ignore any lens and stay object-only
    called = {"n": 0}

    class _W:
        def look_lens(self, *a):
            called["n"] += 1
            return {"ok": True}
        def look(self, *a):
            return None
    monkeypatch.setattr(Brain, "world_lens", lambda self: _W())
    live_mod.world_look(brain, object(), ambient=True, lens="math")
    assert called["n"] == 0                       # lens skipped on ambient


def test_lens_caps_are_no_longer_dormant():
    # with the live dispatch wired, the frontier lenses report on install-state,
    # not the honest-but-hidden "dormant"
    for key in ("math_ocr", "doc_read", "depth_sense", "openvocab_find",
                "scene_segment", "sky_sense"):
        assert key not in C._NOT_WIRED
        st = C.state(C._BY_KEY[key], env={})
        assert st in ("active", "missing", "off", "unsupported")   # never dormant


def test_dream_style_stays_dormant_the_neural_path_needs_a_model():
    # the reachable ?lens=dream path only runs the dependency-free painterly wash;
    # the neural cap must NOT light green just because onnxruntime is importable
    assert "dream_style" in C._NOT_WIRED
    cap = C._BY_KEY["dream_style"]
    assert C.state(cap, env={}) in ("dormant", "missing", "off", "unsupported")
