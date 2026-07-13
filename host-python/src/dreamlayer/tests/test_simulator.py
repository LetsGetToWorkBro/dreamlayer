"""test_simulator.py — the Halo simulator: real stack, virtual glass.

Proves the simulator is the REAL DreamLayer loop end to end: voice → intent →
figment envelopes over the bridge → the reference stage ticking → pixels, plus
the social recall loop and the Privacy Veil, all without hardware.
"""
from __future__ import annotations

import json
import urllib.request

from dreamlayer.simulator import HaloSimulator
from dreamlayer.simulator.server import make_simulator_server


def _png(b: bytes) -> bool:
    return b[:8] == b"\x89PNG\r\n\x1a\n"


def _lit(img) -> bool:
    rgb = img.convert("RGB")
    return rgb.tobytes() != bytes(3 * rgb.width * rgb.height)  # any non-black pixel


# -- the glass ------------------------------------------------------------

def test_ready_frame_is_a_lit_png():
    sim = HaloSimulator()
    assert _png(sim.frame_png())
    assert _lit(sim.frame_image())


# -- a real timer, counting down on the reference stage --------------------

def test_timer_runs_on_the_stage():
    sim = HaloSimulator()
    r = sim.voice("set a timer for 30 seconds")
    assert r["ok"] and "30 seconds" in r["say"]
    st = sim.state()
    assert st["figment"] is not None and st["figment"]["scene"] == "run"
    # the countdown is live: step the stage and the remaining drops
    sim.stage.step(10.0)
    assert abs(sim.state()["figment"]["remaining"] - 20.0) < 1.5
    # the glass draws the figment, and the resolved text carries the clock
    frame = sim.stage.frame()
    joined = " ".join(ln.text for ln in frame.lines)
    assert any(ch.isdigit() for ch in joined)
    assert _lit(sim._paint_figment())
    # run it out — the stage ends and the glass returns to ambient
    sim.stage.step(120.0)
    sim.frame_png()
    assert sim.state()["figment"] is None


def test_timer_cancel_revokes_the_stage():
    sim = HaloSimulator()
    sim.voice("set a timer for 5 minutes")
    assert sim.state()["figment"] is not None
    sim.voice("stop the timer")
    assert sim.state()["figment"] is None


def test_gesture_reaches_the_running_figment():
    sim = HaloSimulator()
    sim.voice("set a timer for 5 minutes")
    # the native timer's long-press is its stop control
    r = sim.gesture("long")
    assert r["handled"]
    sim.frame_png()
    assert sim.state()["figment"] is None


# -- the social loop: introduce → glance → recall ---------------------------

def test_meet_then_glance_recalls():
    sim = HaloSimulator()
    r = sim.voice("this is my colleague Sarah, she runs marketing", look="face-a")
    assert r["ok"] and "Sarah" in r["say"]
    g = sim.glance(look="face-a")
    assert g["ok"] and "Sarah" in g["say"] and "colleague" in g["say"]
    assert g["recall"]["rescue"]["relation"] == "colleague"
    # the identity card landed on the glass
    assert _png(sim.frame_png())
    assert "Sarah" in json.dumps(sim.bridge.last_card)
    # and a stranger's face stays a stranger
    s = sim.glance(look="face-b")
    assert "don't know" in s["say"]


def test_debts_ride_the_same_loop():
    sim = HaloSimulator()
    sim.voice("this is my colleague Sarah", look="face-a")
    sim.voice("Sarah owes me $20")
    g = sim.glance(look="face-a")
    assert "owes you $20" in json.dumps(g["recall"])


# -- the veil ---------------------------------------------------------------

def test_veil_blacks_the_loop_out():
    sim = HaloSimulator()
    sim.veil(True)
    r = sim.voice("I left my bike at the north rack")
    assert r["say"] == "Not while you're incognito."
    # the glass shows the veil, not a card
    assert sim.state()["veiled"]
    sim.veil(False)
    assert sim.voice("I left my bike at the north rack")["ok"]
    assert "north rack" in sim.voice("where's my bike?")["say"]


# -- the whole thing over HTTP ----------------------------------------------

def test_simulator_over_http():
    import threading
    srv = make_simulator_server(host="127.0.0.1", port=7899)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def get(path):
        return urllib.request.urlopen("http://127.0.0.1:7899" + path).read()

    def post(path, body):
        req = urllib.request.Request("http://127.0.0.1:7899" + path,
                                     data=json.dumps(body).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        return json.loads(urllib.request.urlopen(req).read())

    try:
        page = get("/").decode()
        assert "Halo Simulator" in page and "/sim/frame.png" in page
        assert _png(get("/sim/frame.png"))
        r = post("/sim/voice", {"text": "set a timer for 30 seconds"})
        assert r["ok"] and "Timer set" in r["say"]
        st = json.loads(get("/sim/state"))
        assert st["figment"] is not None
        r = post("/sim/voice", {"text": "this is my friend Priya", "look": "face-c"})
        assert "Priya" in r["say"]
        st = json.loads(get("/sim/state"))
        assert "Priya" in st["people"]
        assert post("/sim/veil", {"on": True})["veiled"]
    finally:
        srv.shutdown()
