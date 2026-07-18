"""test_world_lens.py — the World lens run inside the Brain (the phone-as-glasses
stand-in). Covers the WorldLensHost, its VLM-backed recognizer, and the
POST /dreamlayer/brain/look route.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.world_lens import WorldLensHost
from dreamlayer.object_lens.schema import ObjectSighting
from dreamlayer.object_lens.vision_recognizer import (
    VisionSightingRecognizer, parse_sighting_json, frame_to_b64, b64_to_frame)
from dreamlayer.plugins.currency import CurrencyProvider


# --- fakes ------------------------------------------------------------------

class _FakeBackend:
    """A vision backend whose describe()/vision() are injectable per test."""
    def __init__(self, describe_reply="", vision_reply="a mug you own"):
        self._describe_reply = describe_reply
        self._vision_reply = vision_reply
    def describe(self, prompt, image_b64):
        return self._describe_reply
    def vision(self, label, image_b64, want):
        return self._vision_reply


class _FakeBrain:
    def __init__(self, backend=None, incognito=False, caps=("object_lens", "network")):
        self._backend = backend
        self.health = None
        self._incognito = incognito
        self._caps = frozenset(caps)
        self.plugins = None                    # no installed-plugin store in unit tests
    def incognito_now(self):
        return self._incognito
    def plugin_capabilities(self):
        return self._caps


def _noise_frame(seed=0):
    return np.random.RandomState(seed).rand(48, 48, 3).astype("float32")


# --- the recognizer ---------------------------------------------------------

def test_parse_sighting_json_tolerates_prose_and_fences():
    reply = 'Sure!\n```json\n{"label":"espresso cup","confidence":0.8,' \
            '"attributes":{"amount":3.5,"currency":"eur","junk":9}}\n```'
    label, conf, attrs = parse_sighting_json(reply)
    assert label == "espresso cup"
    assert conf == pytest.approx(0.8)
    assert attrs == {"amount": 3.5, "currency": "EUR"}   # junk dropped, code upper


def test_parse_sighting_json_rejects_empty_and_nonjson():
    assert parse_sighting_json('{"label":""}') is None
    assert parse_sighting_json("no json here") is None
    assert parse_sighting_json("") is None


def test_parse_sighting_json_clamps_hostile_amount():
    # inf/NaN would poison CurrencyProvider's float(amount); it must be dropped.
    _, _, attrs = parse_sighting_json('{"label":"x","attributes":{"amount":1e400}}')
    assert "amount" not in attrs


def test_vision_recognizer_falls_back_to_heuristic_when_model_declines():
    frame = _noise_frame()
    rec = VisionSightingRecognizer(lambda p, i: "")     # model gives nothing
    out = rec(frame)
    assert out is not None                              # heuristic ladder answers
    # the heuristic ladder returns (label, conf); ObjectRecognizer accepts that
    assert isinstance(out[0], str) and out[0]


def test_frame_b64_roundtrip():
    frame = (_noise_frame() * 255).astype("uint8")
    b64 = frame_to_b64(frame)
    assert isinstance(b64, str) and b64
    assert getattr(b64_to_frame(b64), "shape", None) == (48, 48, 3)
    assert frame_to_b64("already-b64") == "already-b64"  # str passes through


# --- the host ---------------------------------------------------------------

def test_look_sighting_lights_up_a_registered_connector():
    host = WorldLensHost(_FakeBrain())
    host.object_lens.registry.register(
        CurrencyProvider(home="USD", rates_fetch=lambda a, b: 1.08))
    panel = host.look_sighting(
        ObjectSighting(label="price tag", confidence=0.9,
                       attributes={"amount": 20, "currency": "EUR"}))
    card = panel.to_hud_card()
    assert card["primary"] == "price tag"
    assert any("$21.60" in r["label"] for r in card["rows"])   # 20 EUR → 21.60 USD
    assert "currency" in card["footer"]


def test_look_recognizes_via_vision_and_carries_attributes():
    reply = '{"label":"banknote","confidence":0.7,' \
            '"attributes":{"amount":50,"currency":"JPY"}}'
    host = WorldLensHost(_FakeBrain(backend=_FakeBackend(describe_reply=reply)))
    host.object_lens.registry.register(
        CurrencyProvider(home="USD", rates_fetch=lambda a, b: 0.0064))
    panel = host.look(_noise_frame())
    assert panel is not None
    assert panel.sighting.label == "banknote"
    assert any(r.source == "currency" for r in panel.rows)


def test_look_defers_a_person_to_the_social_lens():
    reply = '{"label":"person","confidence":0.9}'
    host = WorldLensHost(_FakeBrain(backend=_FakeBackend(describe_reply=reply)))
    assert host.look(_noise_frame()) is None            # a human is never panelled
    assert host.look_sighting(ObjectSighting(label="a man", confidence=0.9)) is None


def test_named_stranger_is_deferred_not_identified():
    # THE contract: never identify a stranger. The person-token denylist catches
    # CATEGORIES ("a man") but not IDENTITIES — a VLM that returns a proper NAME
    # (celebrity recognition, or a crafted nametag/caption) must still defer
    # (refute 2026-07-18: "Maya Chen" was named straight onto the glass).
    from dreamlayer.object_lens.recognizer import (
        _names_a_person, _looks_like_a_personal_name)
    assert _looks_like_a_personal_name("Maya Chen") is True
    assert _names_a_person("Taylor Swift") is True
    assert _names_a_person("John Smith") is True
    # objects (lowercase category nouns) still pass — the open-vocab path holds
    assert _names_a_person("espresso machine") is False
    assert _names_a_person("almond milk") is False
    assert _looks_like_a_personal_name("mug") is False
    # end-to-end: a VLM naming a person yields NO panel (REVERT-FAILING)
    reply = '{"label":"Maya Chen","confidence":0.96}'
    host = WorldLensHost(_FakeBrain(backend=_FakeBackend(describe_reply=reply)))
    assert host.look(_noise_frame()) is None


def test_clean_attrs_strips_contact_pii():
    # an object's brand/text must not smuggle a name + contact detail onto the
    # panel (the lanyard/nametag scenario) (refute 2026-07-18).
    from dreamlayer.object_lens.vision_recognizer import _clean_attrs
    out = _clean_attrs({"brand": "Maya Chen 555-123-4567", "text": "reach me@x.com",
                        "title": "The Pragmatic Programmer", "isbn": "9780135957059"})
    assert "brand" not in out                            # phone number → dropped
    assert "text" not in out                             # email → dropped
    assert out["title"] == "The Pragmatic Programmer"    # clean free text kept
    assert out["isbn"] == "9780135957059"                # ISBN digits are not "PII"


def test_b64_to_frame_refuses_a_decompression_bomb(monkeypatch):
    # A tiny solid-colour image can declare huge dimensions and decode to
    # hundreds of MB. Reject on the pixel count BEFORE materialising the array
    # (refute 2026-07-18). Cap lowered so a normal image trips the guard without
    # allocating a real bomb in-test — the LOGIC is what's pinned.
    pytest.importorskip("PIL")
    import io as _io, base64 as _b64
    from PIL import Image
    import dreamlayer.object_lens.vision_recognizer as vr
    buf = _io.BytesIO(); Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "PNG")
    b64 = _b64.b64encode(buf.getvalue()).decode()
    monkeypatch.setattr(vr, "MAX_FRAME_PIXELS", 100)     # 10x10 ceiling
    assert vr.b64_to_frame(b64) is None                  # 64x64 = 4096 > cap → refused
    monkeypatch.setattr(vr, "MAX_FRAME_PIXELS", 1_000_000)
    assert getattr(vr.b64_to_frame(b64), "shape", None) == (64, 64, 3)   # under cap: fine


def test_untrusted_installed_plugins_require_a_sandbox():
    # The world lens is REMOTELY reachable and runs UNTRUSTED installed plugins —
    # on a host with no kernel sandbox they must FAIL CLOSED, not run as a plain
    # subprocess with full OS authority (refute 2026-07-18).
    calls = {}

    class _SpyStore:
        def load_installed(self, host, isolate="untrusted", require_sandbox=None):
            calls["require_sandbox"] = require_sandbox
            return []

    brain = _FakeBrain()
    brain.plugins = _SpyStore()
    WorldLensHost(brain)                                 # __init__ loads installed plugins
    assert calls.get("require_sandbox") is True          # REVERT-FAILING


def test_plugin_network_capability_is_veil_aware():
    # incognito ⇒ no `network` egress capability handed to a plugin (fail-closed),
    # mirroring the orchestrator's hardened grant (refute 2026-07-18: the
    # world-lens grant was blind to the veil).
    veiled = WorldLensHost(_FakeBrain(incognito=True, caps=("object_lens", "network")))
    assert "network" not in veiled._plugin_capabilities()
    live = WorldLensHost(_FakeBrain(incognito=False, caps=("object_lens", "network")))
    assert "network" in live._plugin_capabilities()


class TestPersonGuardLayers:
    """The optional Presidio (text) + detector (visual) layers that harden the
    'never identify a stranger' defence. Injectable, fail-safe: absent both deps
    they are no-ops; present, they can only ADD a deferral."""

    def teardown_method(self):
        from dreamlayer.object_lens import person_guard
        person_guard._analyzer_override = None
        person_guard._detector_override = None
        person_guard.reset_caches()

    def test_text_layer_is_a_noop_when_presidio_absent(self):
        from dreamlayer.object_lens import person_guard
        person_guard.reset_caches()
        person_guard._analyzer_cache = person_guard._NONE   # simulate unavailable
        assert person_guard.label_is_a_person("Maya") is False   # no crash, no defer

    def test_text_layer_defers_a_lone_given_name_via_presidio(self):
        from dreamlayer.object_lens import person_guard
        # a fake Presidio analyzer flagging PERSON — the shape rule can't catch a
        # single lowercase-context given name, but NER can.
        person_guard._analyzer_override = lambda t: (
            [("PERSON", 0.9)] if "maya" in t.lower() else [])
        assert person_guard.label_is_a_person("Maya") is True
        assert person_guard.label_is_a_person("mug") is False

    def test_visual_layer_defers_only_a_DOMINANT_person(self):
        from dreamlayer.object_lens import person_guard
        person_guard._detector_override = lambda f: [("person", 0.95, 0.6)]   # big box
        assert person_guard.frame_is_dominated_by_a_person(object()) is True
        person_guard._detector_override = lambda f: [("person", 0.95, 0.02)]  # bystander
        assert person_guard.frame_is_dominated_by_a_person(object()) is False
        person_guard._detector_override = lambda f: []                         # no person
        assert person_guard.frame_is_dominated_by_a_person(object()) is False

    def test_visual_layer_defers_even_when_the_vlm_says_object(self):
        # a VLM mislabels a person "statue"; the visual detector is ground truth.
        from dreamlayer.object_lens import person_guard
        person_guard._detector_override = lambda f: [("person", 0.95, 0.6)]
        host = WorldLensHost(_FakeBrain(
            backend=_FakeBackend(describe_reply='{"label":"statue","confidence":0.9}')))
        assert host.look(_noise_frame()) is None            # REVERT-FAILING

    def test_both_layers_absent_leaves_object_recognition_intact(self):
        # the fallback (this env): both optional layers unavailable → a real
        # object still recognises normally, nothing over-deferred.
        from dreamlayer.object_lens import person_guard
        person_guard._analyzer_cache = person_guard._NONE
        person_guard._detector_cache = person_guard._NONE
        host = WorldLensHost(_FakeBrain(
            backend=_FakeBackend(describe_reply='{"label":"mug","confidence":0.8}')))
        panel = host.look(_noise_frame())
        assert panel is not None and panel.sighting.label == "mug"


def test_remote_vision_backend_is_gated_and_counted():
    # A REMOTE (off-box) vision backend receiving the wearer's photo IS cloud
    # egress: count it and block it while incognito, don't ship it silently
    # (refute 2026-07-18: the look path never read no_cloud or bumped cloud_calls).
    from dreamlayer.ai_brain.server.world_lens import _BrainVisionRouter

    class _Cfg:
        ollama_url = "http://8.8.8.8:11434"              # PUBLIC host → egress

    class _B:
        def __init__(self):
            self._backend = _FakeBackend(vision_reply="x")
            self.config = _Cfg()
            self.cloud_calls = 0
            self._incog = False

        def incognito_now(self):
            return self._incog

        def bump_cloud_calls(self):
            self.cloud_calls += 1

    b = _B()
    router = _BrainVisionRouter(b)
    frame = (_noise_frame() * 255).astype("uint8")
    router.explain(frame, "mug")
    assert b.cloud_calls == 1                            # remote egress accounted
    b._incog = True
    assert router.explain(frame, "mug") is None          # veiled → no remote vision
    assert b.cloud_calls == 1                            # and not counted again


def test_veiled_look_is_blind():
    host = WorldLensHost(_FakeBrain(incognito=True))
    assert host.veiled() is True
    assert host.look(_noise_frame()) is None
    assert host.look_sighting(
        ObjectSighting(label="mug", confidence=0.9)) is None


def test_ai_explainer_row_when_a_vision_backend_is_present():
    host = WorldLensHost(_FakeBrain(backend=_FakeBackend(vision_reply="a ceramic mug")))
    panel = host.look_sighting(ObjectSighting(label="mug", confidence=0.9), facet="ai")
    assert panel is not None
    assert any("mug" in (r.detail or "") for r in panel.rows)


def test_taste_reads_a_shelf_and_ranks_it():
    shelf = "Green Tea | leaves | 4 | 4.5\nCola | sugar | 2 | 2.0"
    host = WorldLensHost(_FakeBrain(backend=_FakeBackend(describe_reply=shelf)))
    ranking = host.taste(_noise_frame())
    assert ranking is not None and not ranking.unavailable
    assert len(ranking.items) == 2


# --- the route --------------------------------------------------------------

def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "127.0.0.1", server.server_address[1]


def _post(url, body, timeout=10):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_route_deterministic_label_returns_a_panel(tmp_path):
    brain = Brain(tmp_path)
    # register a connector on the (cached) world lens so the look lights it up
    brain.world_lens().object_lens.registry.register(
        CurrencyProvider(home="USD", rates_fetch=lambda a, b: 1.1))
    server, host, port = _serve(brain)
    try:
        status, body = _post(
            f"http://{host}:{port}/dreamlayer/brain/look",
            {"label": "price", "attrs": {"amount": 10, "currency": "EUR"}})
        assert status == 200
        assert body["ok"] is True
        assert body["lens"] == "object"
        assert any("$11.00" in r["label"] for r in body["panel"]["rows"])
    finally:
        server.shutdown()


def test_route_is_blind_while_incognito(tmp_path):
    brain = Brain(tmp_path)
    brain.incognito_now = lambda: True          # type: ignore[method-assign]
    brain._invalidate_world_lens()
    server, host, port = _serve(brain)
    try:
        status, body = _post(
            f"http://{host}:{port}/dreamlayer/brain/look",
            {"label": "mug"})
        assert status == 200
        assert body["ok"] is False
        assert body.get("veiled") is True
    finally:
        server.shutdown()
