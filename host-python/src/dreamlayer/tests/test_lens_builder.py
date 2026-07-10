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

    @pytest.mark.parametrize("recipe", ["interval", "countdown", "checklist", "breathing"])
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
