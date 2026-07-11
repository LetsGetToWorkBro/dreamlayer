"""test_lens_builder.py — the no-code browser lens builder (INNOVATION Category 1).

Two guarantees that matter:
  1. the builder's JS budget constants stay in lockstep with the Python source of
     truth (reality_compiler/v2/figment.py) — no silent drift;
  2. a figment the browser builder produces is accepted by the *real* Python
     budget gate — so "valid in the browser" means valid on the glasses.
Also runs the JS self-test under Node when Node is present.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dreamlayer.reality_compiler.v2 import figment as F
from dreamlayer.reality_compiler.v2.budgets import verify
from dreamlayer.reality_compiler.v2.figment import Figment

LENS = Path(__file__).resolve().parents[4] / "landing" / "assets" / "lens"
JS = LENS / "figment.js"


def _js_const(name: str) -> float:
    """Pull `NAME: <number>` out of the JS budget block."""
    import re
    m = re.search(rf"\b{name}\s*:\s*([0-9.]+)", JS.read_text())
    assert m, f"{name} not found in figment.js"
    return float(m.group(1))


def test_js_budgets_match_the_python_source():
    for name, py in [
        ("MAX_SCENES", F.MAX_SCENES), ("MAX_COUNTERS", F.MAX_COUNTERS),
        ("MAX_LINES", F.MAX_LINES), ("MAX_TEXT_LEN", F.MAX_TEXT_LEN),
        ("MAX_PULSE_HZ", F.MAX_PULSE_HZ), ("MIN_SCENE_SEC", F.MIN_SCENE_SEC),
        ("MAX_NAME_LEN", F.MAX_NAME_LEN), ("MAX_BRANCHES", F.MAX_BRANCHES),
        ("MAX_GLYPHS", F.MAX_GLYPHS), ("MAX_GLYPH_POINTS", F.MAX_GLYPH_POINTS),
    ]:
        assert _js_const(name) == float(py), f"{name} drifted: JS {_js_const(name)} vs py {py}"


def test_js_palette_tokens_match():
    text = JS.read_text()
    for tok in F.COLOR_TOKENS:
        assert f'"{tok}"' in text, f"palette token {tok} missing from figment.js"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
class TestUnderNode:
    def test_selftest_passes(self):
        r = subprocess.run(["node", "figment.selftest.js"], cwd=LENS,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    @pytest.mark.parametrize("recipe", ["interval", "countdown", "checklist",
                                        "breathing", "reps", "focus", "score"])
    def test_a_browser_built_figment_passes_the_real_gate(self, recipe):
        # dump the template the browser would emit, load it with the real
        # Figment, and run the real budget verifier — the strongest parity check
        out = subprocess.run(
            ["node", "-e",
             f"console.log(JSON.stringify(require('./figment.js').templates.{recipe}()))"],
            cwd=LENS, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        data = json.loads(out.stdout)
        fig = Figment.from_dict(data)
        report = verify(fig)
        assert report.ok, f"{recipe} rejected by the real gate: {report.violations}"

    @pytest.mark.parametrize("show", ["headControl", "mandala", "world",
                                      "keep", "fusion", "whisper", "ask",
                                      "secondSight", "tethered", "threshold",
                                      "ember", "coach"])
    def test_a_tutorial_showcase_passes_the_real_gate(self, show):
        # the "what's possible" tour loads these live — they push the whole
        # grammar (gestures, guards, paint, cadence, world-triggers, record)
        # and must still clear the exact same budget proof
        out = subprocess.run(
            ["node", "-e",
             f"console.log(JSON.stringify(require('./figment.js').showcases.{show}()))"],
            cwd=LENS, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        fig = Figment.from_dict(json.loads(out.stdout))
        report = verify(fig)
        assert report.ok, f"{show} rejected by the real gate: {report.violations}"

    # (show, events that reach the {slot} scene before the host pushes text)
    @pytest.mark.parametrize("show,setup", [
        ("whisper", []), ("ask", ["double"]), ("secondSight", ["long"]),
        ("ember", []), ("coach", []),
    ])
    def test_slot_fed_showcase_renders_the_hosts_text(self, show, setup):
        # the "live feed" is real: these showcases show {slot}, and the host
        # (Brain/camera) pushes text into it via a "text" event. Prove the
        # reference interpreter actually surfaces that text on a line.
        from dreamlayer.reality_compiler.v2.interpreter import Stage
        out = subprocess.run(
            ["node", "-e",
             f"console.log(JSON.stringify(require('./figment.js').showcases.{show}()))"],
            cwd=LENS, capture_output=True, text=True)
        fig = Figment.from_dict(json.loads(out.stdout))
        st = Stage(fig)
        for ev in setup:
            st.inject(ev)                          # reach the answer/seen scene
        st.inject("text", "HELLO WORLD")           # the host streams a line in
        assert any("HELLO WORLD" in ln.text for ln in st.frame().lines), \
            f"{show} did not surface the host's slot text"


# -- the Brain import endpoint (Deploy to my Brain) ---------------------------

class TestBrainImport:
    def _brain(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        return Brain(tmp_path)

    def _figment_dict(self):
        f = Figment(name="Imported", initial="a")
        f.add_scene(F.Scene(id="a", duration_sec=10.0,
                            lines=[F.TextLine("HI", row=0)],
                            on_timeout=[F.Transition(target=F.END)]))
        return f.to_dict()

    def test_import_verifies_signs_and_deploys(self, tmp_path):
        brain = self._brain(tmp_path)
        out = brain.rc_import(self._figment_dict())
        assert out["ok"] is True and out["safety"]["ok"] is True
        assert brain._rc_active == out["id"]              # on stage now

    def test_import_rejects_a_non_figment(self, tmp_path):
        brain = self._brain(tmp_path)
        assert brain.rc_import({"nonsense": True})["ok"] is False

    def test_import_rechecks_the_proof(self, tmp_path):
        brain = self._brain(tmp_path)
        bad = self._figment_dict()
        bad["scenes"]["a"]["pulse"] = {"window_sec": 5, "rate_hz": 99.0,
                                       "color": "accent_attention"}
        out = brain.rc_import(bad)
        assert out["ok"] is False                          # the Brain re-checks; 99Hz is out


# -- Ask Juno: describe a lens, get a verified figment back -------------------

class TestAskJuno:
    def _brain(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        return Brain(tmp_path)

    def test_compose_drafts_a_verified_figment(self, tmp_path):
        brain = self._brain(tmp_path)
        out = brain.rc_compose("a 5 minute countdown that pulses at the end")
        assert out["ok"] is True
        assert out["scenes"] >= 1
        # the returned figment must survive the real gate — it's what the
        # builder loads, then re-checks again on deploy
        fig = Figment.from_dict(out["figment"])
        assert verify(fig).ok

    def test_compose_does_not_deploy(self, tmp_path):
        brain = self._brain(tmp_path)
        brain.rc_compose("interval timer 3 minutes work 1 minute rest")
        assert getattr(brain, "_rc_active", None) is None   # composing never stages

    def test_compose_on_gibberish_is_a_friendly_miss(self, tmp_path):
        brain = self._brain(tmp_path)
        out = brain.rc_compose("qwx zzptmn frobnicate")
        assert out["ok"] is False and out["unmatched"] is True
        assert out["examples"]                              # offers a way forward

    def test_compose_on_empty_prompt(self, tmp_path):
        brain = self._brain(tmp_path)
        out = brain.rc_compose("   ")
        assert out["ok"] is False and out["unmatched"] is True


# -- the real hardware loop: Brain feeds the live lens, closes emit→answer ----

class TestBrainLensLoop:
    def _brain(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        return Brain(tmp_path)

    def _deploy_slot_lens(self, brain):
        # a minimal lens that shows {slot}: what the world-facing showcases are
        fig = Figment(name="Slotty", initial="show")
        fig.add_scene(F.Scene(id="show", lines=[F.TextLine("{slot}", row=1)],
                              on={"double": F.Transition(target=F.END)}))
        out = brain.rc_import(fig.to_dict())
        assert out["ok"] and brain._rc_active == out["id"]
        return out["id"]

    def test_feed_streams_text_to_the_live_lens(self, tmp_path):
        brain = self._brain(tmp_path)
        active = self._deploy_slot_lens(brain)
        before = len(brain.rc.deployer.sent)
        r = brain.rc_feed("Hola mundo", source="translate")
        assert r["ok"] and r["text"] == "Hola mundo" and r["active"] == active
        # the device actually received a text envelope carrying that line
        sent = brain.rc.deployer.sent[before:]
        assert any(e.get("t") == "figment_text" and e.get("text") == "Hola mundo"
                   for e in sent)

    def test_feed_clamps_to_one_glass_line(self, tmp_path):
        brain = self._brain(tmp_path)
        self._deploy_slot_lens(brain)
        r = brain.rc_feed("x" * 200)
        assert r["ok"] and len(r["text"]) <= F.MAX_TEXT_LEN

    def test_feed_refused_with_no_lens_on_stage(self, tmp_path):
        brain = self._brain(tmp_path)
        assert brain.rc_feed("anything")["ok"] is False

    def test_emit_ask_runs_the_brain_and_answers_on_glass(self, tmp_path):
        from dreamlayer.ai_brain.schema import Answer
        brain = self._brain(tmp_path)
        active = self._deploy_slot_lens(brain)
        # stand in for the Brain's recall so the test is deterministic
        seen = {}
        brain.ask = lambda q: (seen.update(q=q) or Answer("Lease due Fri 14th", tier="device"))
        r = brain.rc_emit("ask", "when is my lease due?")
        assert r["ok"] and r["tag"] == "ask"
        assert seen["q"] == "when is my lease due?"           # the question reached the Brain
        assert r["answer"] == "Lease due Fri 14th" and r["tier"] == "device"
        # and the answer was pushed onto the glass
        assert any(e.get("t") == "figment_text" and "Lease due" in e.get("text", "")
                   for e in brain.rc.deployer.sent)

    def test_emit_with_payload_streams_to_the_slot(self, tmp_path):
        brain = self._brain(tmp_path)
        self._deploy_slot_lens(brain)
        r = brain.rc_emit("look", "Monstera deliciosa")
        assert r["ok"] and r["tag"] == "look" and r["text"].startswith("Monstera")

    def test_emit_refused_with_no_lens_or_empty_tag(self, tmp_path):
        brain = self._brain(tmp_path)
        assert brain.rc_emit("ask", "hi")["ok"] is False       # nothing on stage
        self._deploy_slot_lens(brain)
        assert brain.rc_emit("")["ok"] is False                # empty tag


# -- the builder page itself --------------------------------------------------

def test_builder_page_is_wired():
    page = (LENS.parents[1] / "lens-builder.html").read_text(encoding="utf-8")
    assert "assets/lens/figment.js" in page          # loads the logic module
    assert "This behavior <b>CANNOT</b>" in page or "This behavior" in page
    assert "/dreamlayer/rc/import" in page            # deploy hits the real endpoint
    assert "X-DreamLayer-Token" in page               # sends the Brain token
    # the three follow-ons: advanced scene-graph, publish, same-origin
    assert 'data-mode="advanced"' in page             # Simple ↔ Advanced modes
    assert "/api/figments/submit" in page             # publish to the store
    assert "__DL_BUILD__" in page                     # same-origin (Brain-served) mode
    assert 'id="graph"' in page                        # the transition diagram
    assert 'id="paint"' in page                        # the paint-on-your-lens mode
    assert "/dreamlayer/rc/compose" in page            # Ask Juno hits the compose endpoint
    assert "composeLocal" in page                      # and degrades client-side off-Brain
    assert 'id="tour"' in page and "runShowcase" in page   # the "what's possible" tutorial
    assert "dl_tour_seen" in page                      # first-run gating so it isn't nagware


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_registry_figment_submit_route():
    api = Path(__file__).resolve().parents[4] / "registry-api"
    r = subprocess.run(["node", "worker.figments.test.mjs"], cwd=api,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# -- Brain-served builder (same-origin, no CORS) ------------------------------

class TestBrainServesBuilder:
    def test_resolver_finds_the_builder(self):
        from dreamlayer.ai_brain.server.server import _builder_dir, _builder_asset
        d = _builder_dir()
        assert d is not None and (d / "lens-builder.html").exists()
        assert "LensKit" in (_builder_asset("figment.js") or "")

    def test_page_injects_same_origin_and_rewrites_js(self):
        from dreamlayer.ai_brain.server.server import _builder_page
        html = _builder_page("tok-123")
        assert html is not None
        assert "/dreamlayer/build/figment.js" in html      # js path rewritten
        assert "./assets/lens/figment.js" not in html
        assert "__DL_BUILD__" in html and "tok-123" in html # same-origin + token
        assert '"sameOrigin": true' in html

    def test_page_omits_token_off_localhost(self):
        from dreamlayer.ai_brain.server.server import _builder_page
        assert '"token": ""' in _builder_page("")


# -- an ADVANCED-editor graph (not just a template) passes the real gate -------

@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
class TestAdvancedGraphParity:
    def _build(self, script: str) -> dict:
        out = subprocess.run(["node", "-e", script], cwd=LENS,
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def test_a_hand_wired_graph_passes_the_python_gate(self):
        # emptyFigment (s0 timed→end) + an event-only s1, cross-wired — the exact
        # shape the Advanced editor produces, not a bundled template.
        data = self._build(
            "var K=require('./figment.js');"
            "var f=K.emptyFigment();"
            "var s1=K.addBlankScene(f);"
            "K.setTransition(f.scenes.s0,'double',s1.id);"   # s0 --double--> s1
            "K.setTransition(s1,'double','@end');"           # s1 --double--> end
            "console.log(JSON.stringify(f));")
        report = verify(Figment.from_dict(data))
        assert report.ok, report.violations             # browser 'valid' == on-glass valid

    def test_js_and_python_agree_on_an_invalid_graph(self):
        # a timeout transition with no duration is illegal in BOTH — the JS must
        # not call it safe when Python would reject it (the dangerous direction).
        script = (
            "var K=require('./figment.js');"
            "var f=K.emptyFigment();"
            "var s1=K.addBlankScene(f);"                    # untimed
            "K.setTransition(s1,'timeout','@end');"          # on_timeout w/o duration
            "console.log(JSON.stringify({ok:K.validate(f).ok, fig:f}));")
        got = self._build(script)
        assert got["ok"] is False                            # JS rejects it
        assert verify(Figment.from_dict(got["fig"])).ok is False   # so does Python

    def test_orphaned_countdown_tick_is_caught_both_sides(self):
        # un-timing a scene must not leave tick="countdown" behind — JS and the
        # Python gate both reject a countdown on an untimed scene (audit #2).
        script = (
            "var K=require('./figment.js');"
            "var f=K.emptyFigment();"                        # s0 timed + tick countdown
            "delete f.scenes.s0.duration_sec;"               # untime it, leave the tick
            "delete f.scenes.s0.on_timeout;"
            "console.log(JSON.stringify({ok:K.validate(f).ok, fig:f}));")
        got = self._build(script)
        assert got["ok"] is False                            # JS rejects the orphaned tick
        assert verify(Figment.from_dict(got["fig"])).ok is False   # so does Python


# -- the Brain serves the builder over HTTP (same-origin, no CORS) -------------

class TestBuildRouteHttp:
    def _live(self, tmp_path):
        from dreamlayer.tests.test_ai_brain_server import LiveBrain
        return LiveBrain(tmp_path)

    def test_build_page_and_asset_served(self, tmp_path):
        import urllib.request
        lb = self._live(tmp_path)
        try:
            resp = urllib.request.urlopen(lb.url + "/dreamlayer/build")
            page = resp.read().decode()
            assert "__DL_BUILD__" in page and "/dreamlayer/build/figment.js" in page
            # 127.0.0.1 is localhost → the token is injected (same as the panel)
            assert '"token": "tok"' in page
            # SECURITY: this page carries the token, so it must NOT be readable
            # cross-origin — no Access-Control-Allow-Origin on the HTML/JS.
            assert resp.headers.get("Access-Control-Allow-Origin") is None
            jsresp = urllib.request.urlopen(lb.url + "/dreamlayer/build/figment.js")
            assert "LensKit" in jsresp.read().decode()
            assert jsresp.headers.get("Access-Control-Allow-Origin") is None
        finally:
            lb.stop()

    def test_feed_and_emit_routes_close_the_loop_over_http(self, tmp_path):
        import json as _json, urllib.error, urllib.request
        lb = self._live(tmp_path)

        def post(pathname, body, token="tok"):
            hdr = {"Content-Type": "application/json"}
            if token:
                hdr["X-DreamLayer-Token"] = token
            req = urllib.request.Request(lb.url + pathname,
                                         data=_json.dumps(body).encode(), headers=hdr)
            try:
                return _json.loads(urllib.request.urlopen(req).read())
            except urllib.error.HTTPError as e:
                return {"_status": e.code}

        try:
            # deploy a {slot} lens, then feed it and close an emit — over HTTP
            fig = Figment(name="Slotty", initial="show")
            fig.add_scene(F.Scene(id="show", lines=[F.TextLine("{slot}", row=1)],
                                  on={"double": F.Transition(target=F.END)}))
            assert post("/dreamlayer/rc/import", {"figment": fig.to_dict()})["ok"]
            assert post("/dreamlayer/rc/feed", {"text": "Hola"})["text"] == "Hola"
            emitted = post("/dreamlayer/rc/emit", {"tag": "look", "text": "Monstera"})
            assert emitted["ok"] and emitted["tag"] == "look"
            # token-gated: no token → 401
            assert post("/dreamlayer/rc/feed", {"text": "x"}, token=None)["_status"] == 401
        finally:
            lb.stop()

    def test_the_api_sends_no_cors_so_a_drive_by_page_cant_read_it(self, tmp_path):
        # SECURITY: the Brain is a local token-authed API (default token empty).
        # No _json response may carry Access-Control-Allow-Origin, or a page the
        # wearer visits could read backup/token/memory cross-origin. One-click
        # deploy works only because the builder is served *same-origin*.
        import urllib.error, urllib.request
        lb = self._live(tmp_path)
        try:
            req = urllib.request.Request(lb.url + "/dreamlayer/status",
                                         headers={"X-DreamLayer-Token": "tok"})
            try:
                r = urllib.request.urlopen(req)
            except urllib.error.HTTPError as e:
                r = e
            assert r.headers.get("Access-Control-Allow-Origin") is None
        finally:
            lb.stop()
