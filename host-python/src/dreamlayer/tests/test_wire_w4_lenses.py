"""W4 — the frontier lenses are reachable: math/doc/depth OCR, the sky, weather,
aircraft, dream stylization, all triggerable from the orchestrator.

The N-waves shipped these engines but nothing wired a trigger to them. These
tests pin the glue WorldLensOps adds: each lazily builds its engine once, is
veil-gated at the door, sends the right HUD line when there's something to say,
and no-ops cleanly with no wheel / no data / no network. Offline throughout —
fake engines are injected into the lazy cache.
"""
from __future__ import annotations

from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _orc():
    from dreamlayer.orchestrator.orchestrator import Orchestrator
    return Orchestrator(FakeBridge())


def _cards(orc):
    return [c for c in orc.bridge.raw
            if isinstance(c, dict) and c.get("t") == "card"]


FRAME = [[0, 0, 0]]


# ---- math / doc / depth OCR ----------------------------------------------

def test_read_math_speaks_latex():
    o = _orc()

    class _Math:
        ready = True
        def read_math(self, frame):
            return r"\int_0^1 x\,dx"
    o._frontier["math"] = _Math()
    out = o.read_math(FRAME)
    assert out == r"\int_0^1 x\,dx"
    assert any("int" in c.get("primary", "") for c in _cards(o))


def test_read_math_empty_without_engine():
    o = _orc()
    assert o.read_math(FRAME) == ""
    assert _cards(o) == []


def test_read_math_veil_gated():
    o = _orc()

    class _Math:
        ready = True
        def read_math(self, frame):
            return "x^2"
    o._frontier["math"] = _Math()
    o.set_incognito(True)
    assert o.read_math(FRAME) == ""


def test_read_document_returns_blocks_and_speaks():
    o = _orc()

    class _Doc:
        ready = True
        def read_doc(self, frame):
            return {"text": "Passport renewal form", "blocks": ["Passport", "form"]}
    o._frontier["doc"] = _Doc()
    doc = o.read_document(FRAME)
    assert doc["text"] == "Passport renewal form"
    assert any("Passport" in c.get("primary", "") for c in _cards(o))


def test_sense_depth_harks_when_close():
    o = _orc()

    class _Depth:
        ready = True
        def nearest_relative(self, frame):
            return 0.92
    o._frontier["depth"] = _Depth()
    prox = o.sense_depth(FRAME)
    assert prox == 0.92
    cards = _cards(o)
    assert cards and cards[0]["importance"] == "urgent"
    assert "close" in cards[0]["primary"].lower()


def test_sense_depth_silent_when_far():
    o = _orc()

    class _Depth:
        ready = True
        def nearest_relative(self, frame):
            return 0.30
    o._frontier["depth"] = _Depth()
    assert o.sense_depth(FRAME) == 0.30
    assert _cards(o) == []


# ---- the sky lens --------------------------------------------------------

def test_look_up_whispers_the_sky():
    o = _orc()

    class _Sky:
        def night_sky(self, lat, lon, when_ts=None):
            return {"planets": [("Mars", 30.0, 120.0)], "iss_minutes": None}
    o._frontier["sky"] = _Sky()
    sky = o.look_up(40.7, -74.0)
    assert sky["planets"]
    assert any("Mars" in c.get("primary", "") for c in _cards(o))


def test_look_up_empty_without_ephemeris():
    o = _orc()
    o._frontier["sky"] = None       # default_sky_lens returned None (no data)
    assert o.look_up(40.7, -74.0) == {}


# ---- weather + skywatch (EGRESS, veil-gated) -----------------------------

def test_weather_speaks_and_is_veil_gated(monkeypatch):
    o = _orc()
    import dreamlayer.plugins.open_meteo as om
    monkeypatch.setattr(om, "current_weather",
                        lambda lat, lon, fetch_fn=None: {
                            "sky": "clear", "temp_c": 18,
                            "today": {"hi": 22, "rain_pct": 10}})
    w = o.weather(40.7, -74.0)
    assert w and w["sky"] == "clear"
    assert any("degrees" in c.get("primary", "").lower() for c in _cards(o))
    # veil closes → no egress, no card
    o.bridge.raw.clear()
    o.set_incognito(True)
    assert o.weather(40.7, -74.0) is None
    assert _cards(o) == []


def test_skywatch_names_the_plane(monkeypatch):
    o = _orc()
    import dreamlayer.plugins.skywatch_adsb as sw
    monkeypatch.setattr(sw, "overhead",
                        lambda lat, lon, fetch_fn=None: {
                            "callsign": "BA286", "type": "777",
                            "alt_ft": 34000, "dist_km": 12})
    p = o.skywatch(40.7, -74.0)
    assert p["callsign"] == "BA286"
    assert any("BA286" in c.get("primary", "") for c in _cards(o))


def test_skywatch_veil_gated():
    o = _orc()
    o.set_incognito(True)
    assert o.skywatch(40.7, -74.0) is None


# ---- dream stylizer ------------------------------------------------------

def test_dream_frame_runs_the_stylizer():
    o = _orc()

    class _Styl:
        def stylize(self, frame):
            return "STYLIZED"
    o._frontier["dream_style"] = _Styl()
    assert o.dream_frame(FRAME) == "STYLIZED"


def test_dream_frame_passes_through_on_failure():
    o = _orc()

    class _Styl:
        def stylize(self, frame):
            raise RuntimeError("no runtime")
    o._frontier["dream_style"] = _Styl()
    assert o.dream_frame(FRAME) == FRAME


# ---- lazy build + glance routing -----------------------------------------

def test_frontier_engine_built_once():
    o = _orc()
    calls = {"n": 0}

    def _factory():
        calls["n"] += 1
        return object()
    o._frontier_lens("k", _factory)
    o._frontier_lens("k", _factory)
    assert calls["n"] == 1


def test_glance_routes_to_frontier_lenses():
    o = _orc()
    seen = {}

    class _Math:
        ready = True
        def read_math(self, frame):
            seen["math"] = True
            return "1+1"
    o._frontier["math"] = _Math()
    o.choose_glance("read_math", FRAME)
    assert seen.get("math")
