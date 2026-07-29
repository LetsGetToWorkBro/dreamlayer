"""test_brain_scholar_wiring.py — Scholar, reachable from the phone at last.

Scholar was outside the Brain's import closure entirely: not merely uncalled
but unloadable, so a look at a test question, a form or a page of legal
language could not reach it however complete the lens was. It needed a home,
not a rewrite — `read_fn` is injected and the lens is pure.

The bar is the same one the rest of this audit uses, and the reason it is not
"the object constructs": these tests drive `POST /dreamlayer/scholar` with a
real JPEG through a real `Brain`, with a fake vision backend standing in for
the model. What is being pinned is the wiring — the seam is fed a prompt and a
frame, the reply is parsed, the Veil is honoured, and a Brain with no vision
tier says so instead of guessing.
"""
from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import BrainConfig

PIL = pytest.importorskip("PIL", reason="frame decode needs Pillow")


def _jpeg(w=320, h=240) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (90, 110, 130)).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeVision:
    """Stands in for the vision backend at the one method Scholar's seam uses.

    `WorldLensHost._describe` calls `backend.describe(prompt, image_b64)`, so
    this records the prompt — the test can then assert Scholar's real prompt
    reached the model rather than some placeholder.
    """

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list = []

    def describe(self, prompt, image_b64):
        self.prompts.append(prompt)
        return self.reply


class _Live:
    def __init__(self, tmp_path, reply=None, token="tok"):
        cfg = tmp_path / "cfg"
        cfg.mkdir(exist_ok=True)
        BrainConfig(token=token).save(cfg)
        self.brain = Brain(cfg)
        self.vision = _FakeVision(reply) if reply is not None else None
        self.brain._backend = self.vision
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token}

    def read(self, mode="answer", q="", frame=None):
        req = urllib.request.Request(
            f"{self.url}/dreamlayer/scholar?mode={mode}&q={q}",
            data=frame if frame is not None else _jpeg(),
            headers={"Content-Type": "image/jpeg", **self.h})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, None

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _no_db_override(monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)


class TestScholarIsReachable:

    def test_the_lens_is_in_the_brains_import_closure_now(self):
        import subprocess
        import sys
        from pathlib import Path
        script = Path(__file__).resolve().parents[4] / "scripts" / "lens_reachability.py"
        if not script.exists():
            pytest.skip("checker not on disk")
        out = subprocess.run([sys.executable, str(script)],
                             capture_output=True, text=True).stdout
        unreachable = out.split("UNREACHABLE", 1)[-1].split("reachable (", 1)[0]
        assert "Scholar" not in unreachable

    def test_the_brain_builds_one(self, tmp_path):
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        BrainConfig(token="tok").save(cfg)
        wl = Brain(cfg).world_lens()
        assert wl is not None and wl.scholar is not None


class TestScholarAnswers:

    def test_a_question_in_view_comes_back_answered(self, tmp_path):
        lb = _Live(tmp_path, reply="ANSWER: 42\nWHY: it is the sum of the row")
        try:
            st, body = lb.read("answer")
            assert st == 200, st
            assert body["ok"] is True, body
            assert body["primary"] == "42"
            assert body["detail"] == "it is the sum of the row"
            assert body["card"]["type"] == "ScholarCard"
        finally:
            lb.stop()

    def test_the_lenss_real_prompt_reaches_the_model(self, tmp_path):
        """The seam is only wired if Scholar's own prompt is what goes out. A
        route that sent the object-lens prompt instead would still return a
        parsed card and still look like it worked."""
        lb = _Live(tmp_path, reply="ANSWER: 42")
        try:
            lb.read("answer", q="what+is+the+total")
            assert lb.vision.prompts, "the vision seam was never called"
            sent = lb.vision.prompts[0]
            assert "ANSWER:" in sent and "WHY:" in sent, sent
            assert "what is the total" in sent, sent
        finally:
            lb.stop()

    def test_a_form_comes_back_field_by_field(self, tmp_path):
        lb = _Live(tmp_path, reply=(
            "SUMMARY: a change-of-address form\n"
            "FIELD: Previous address — where you lived before this month\n"
            "FIELD: Effective date — the day the post should start following you"))
        try:
            st, body = lb.read("form")
            assert st == 200 and body["ok"], body
            assert body["primary"] == "a change-of-address form"
            assert len(body["items"]) == 2, body["items"]
            assert body["items"][0]["label"] == "Previous address"
        finally:
            lb.stop()

    def test_dense_text_comes_back_in_plain_words(self, tmp_path):
        lb = _Live(tmp_path, reply=(
            "GIST: You are agreeing to a 24-month term.\n"
            "- Cancelling early costs the remaining months"))
        try:
            st, body = lb.read("explain")
            assert st == 200 and body["ok"], body
            assert "24-month" in body["primary"]
            assert body["items"] == ["Cancelling early costs the remaining months"]
        finally:
            lb.stop()

    def test_the_phones_body_shape_works_as_well_as_the_browsers(self, tmp_path):
        """Two real clients post two different bodies: the browser Live Lens
        sends a bare JPEG, the phone sends `{"image": "<base64>"}`. A route
        that accepted only one would be reachable from one surface and not the
        other, which is the whole complaint this audit is about — and the
        raw-bytes tests above would not have noticed."""
        import base64
        lb = _Live(tmp_path, reply="ANSWER: 42")
        try:
            body = json.dumps({"image": base64.b64encode(_jpeg()).decode()})
            st, out = lb.read("answer", frame=body.encode())
            assert st == 200, st
            assert out["ok"] is True, out
            assert out["primary"] == "42"
        finally:
            lb.stop()

    def test_a_json_body_with_no_image_is_refused_not_decoded_as_pixels(
            self, tmp_path):
        lb = _Live(tmp_path, reply="ANSWER: 42")
        try:
            st, out = lb.read("answer", frame=b'{"mode": "answer"}')
            assert st == 200 and out["ok"] is False, out
            assert out["reason"] == "unreadable frame"
        finally:
            lb.stop()

    def test_an_unknown_mode_reads_as_answer_rather_than_erroring(self, tmp_path):
        lb = _Live(tmp_path, reply="ANSWER: 42")
        try:
            st, body = lb.read("nonsense")
            assert st == 200 and body["mode"] == "answer", body
        finally:
            lb.stop()


class TestScholarIsHonestWhenItCannotRead:

    def test_no_vision_tier_says_so_instead_of_guessing(self, tmp_path):
        """With no backend the lens must return its "Connect a Brain to read
        this" state. An empty string parsed as an answer would put a blank card
        on the glass and call it a read."""
        lb = _Live(tmp_path)                      # no fake backend at all
        try:
            st, body = lb.read("answer")
            assert st == 200
            assert body["ok"] is False, body
            assert "Brain" in body["detail"], body
        finally:
            lb.stop()

    def test_the_veil_stops_the_read_before_the_model(self, tmp_path,
                                                      monkeypatch):
        lb = _Live(tmp_path, reply="ANSWER: 42")
        try:
            monkeypatch.setattr(lb.brain, "incognito_now", lambda: True)
            st, body = lb.read("answer")
            assert st == 200 and body["ok"] is False, body
            assert lb.vision.prompts == [], (
                "a frame reached the vision model while the veil was down")
        finally:
            lb.stop()

    def test_an_unreadable_frame_is_refused_not_parsed(self, tmp_path):
        lb = _Live(tmp_path, reply="ANSWER: 42")
        try:
            st, body = lb.read("answer", frame=b"not an image at all")
            assert st == 200 and body["ok"] is False, body
            assert body["reason"] == "unreadable frame"
        finally:
            lb.stop()

    def test_the_route_needs_the_token(self, tmp_path):
        lb = _Live(tmp_path, reply="ANSWER: 42")
        try:
            lb.h = {}
            st, _ = lb.read("answer")
            assert st in (401, 403), st
        finally:
            lb.stop()
