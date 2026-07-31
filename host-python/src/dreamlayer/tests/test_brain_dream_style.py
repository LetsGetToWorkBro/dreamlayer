"""`dream_style` — see the world as a painting, and actually SEE it.

Two separate failures, either of which alone made the capability unreachable.

THE PAINTING WAS THROWN AWAY. `look_lens("dream")` computed a styled frame and
returned `{"ok": …, "styled": true, "neural": …}` — booleans, no pixels — and
`renderLens` had no `"dream"` case at all, so a dream look fell to the default arm
and drew the word "done". The one lens whose entire output is an image was the one
lens that returned none. "See the world as a painting" is not deliverable as a
boolean.

THE MODEL COULD NOT BE SET. The neural painter's ONNX path came only from
`$DL_DREAM_MODEL`. The bundled .app has no environment of its own to edit, so a
shipped feature was reachable to developers and to nobody else — the pure form of
"technically wired, unreachable from any surface the product ships".

Both are fixed, and the capability is promoted on PROOF: onnxruntime importing
says nothing about a model loading, and a loaded session can still fail on a
frame, so the flag is set only once the neural painter has genuinely produced a
picture — then re-checked against the configured path, because "it worked once
this process" is not "it works now".
"""
from __future__ import annotations

import base64
import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.world_lens import DREAM_MAX_SIDE

LIVE = (pathlib.Path(__file__).resolve().parents[1]
        / "ai_brain" / "server" / "live.py")
PANEL = (pathlib.Path(__file__).resolve().parents[1]
         / "ai_brain" / "server" / "panel.py")


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


@pytest.fixture
def frame():
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    # not flat: a solid colour survives every filter identically, so a painting
    # that did nothing would look like a painting that worked
    return np.random.default_rng(7).integers(0, 255, (64, 48, 3), dtype="uint8")


def _look(brain, frame):
    return brain.world_lens().look_lens(frame, "dream")


class TestThePaintingComesBack:

    def test_a_dream_look_returns_an_image(self, brain, frame):
        """The whole point, and what the branch used to discard."""
        out = _look(brain, frame)
        assert out["ok"] is True, out
        assert out["image"], "the painting was computed and thrown away"
        raw = base64.b64decode(out["image"])
        assert raw[:2] == b"\xff\xd8", "not a JPEG"

    def test_the_image_is_the_PAINTING_not_the_original_frame(self, brain, frame):
        """A branch that returned the input would pass every shape check above."""
        from dreamlayer.object_lens.vision_recognizer import frame_to_b64
        out = _look(brain, frame)
        assert out["image"] != frame_to_b64(frame, max_side=DREAM_MAX_SIDE)

    def test_the_painting_is_bounded_in_size(self, brain):
        """A few-megapixel phone frame re-encoded whole is megabytes of base64 over
        the LAN for a picture that lands in a 256 px circle."""
        np = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")
        big = np.random.default_rng(3).integers(0, 255, (1400, 2000, 3), dtype="uint8")
        out = _look(brain, big)
        import io
        img = Image.open(io.BytesIO(base64.b64decode(out["image"])))
        assert max(img.size) <= DREAM_MAX_SIDE, img.size

    def test_the_aspect_ratio_survives_the_downscale(self, brain):
        """A painting stretched to a square is a different picture from the one
        the wearer looked at."""
        np = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")
        import io
        wide = np.random.default_rng(5).integers(0, 255, (400, 1600, 3), dtype="uint8")
        out = _look(brain, wide)
        img = Image.open(io.BytesIO(base64.b64decode(out["image"])))
        assert abs((img.size[0] / img.size[1]) - 4.0) < 0.05, img.size

    def test_the_shared_encoder_still_resizes_NOTHING_by_default(self):
        """`frame_to_b64` grew `max_side` for this feature, and its other callers
        feed frames to VISION MODELS.

        A default that bounded them would shrink every image a VLM is asked to
        recognise — degrading recognition badly and erroring nowhere, so nothing
        would report it. Changing the default from 0 to 64 survived every test in
        this file until this one existed: the dream path passes `max_side`
        explicitly, so its own assertions could not see the change.
        """
        np = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")
        import io
        from dreamlayer.object_lens.vision_recognizer import frame_to_b64
        big = np.random.default_rng(11).integers(0, 255, (700, 900, 3), dtype="uint8")
        img = Image.open(io.BytesIO(base64.b64decode(frame_to_b64(big))))
        assert img.size == (900, 700), img.size

    def test_a_small_frame_is_not_upscaled(self, brain, frame):
        """`max_side` is a ceiling, not a target — blowing a 64 px frame up to 640
        would invent detail that is not there."""
        Image = pytest.importorskip("PIL.Image")
        import io
        out = _look(brain, frame)
        img = Image.open(io.BytesIO(base64.b64decode(out["image"])))
        assert img.size == (48, 64), img.size

    def test_ok_follows_the_IMAGE_not_the_array(self, brain, frame, monkeypatch):
        """An encode that fails leaves the wearer nothing to look at. Reporting
        `ok: true` there would be the same empty success this whole change is
        about."""
        import dreamlayer.object_lens.vision_recognizer as VR
        monkeypatch.setattr(VR, "frame_to_b64", lambda *a, **k: None)
        out = _look(brain, frame)
        assert out["ok"] is False
        assert out["image"] == ""
        assert out["styled"] is True, "the array WAS painted — say so"

    def test_an_unreadable_frame_is_a_miss_not_a_crash(self, brain):
        out = _look(brain, object())
        assert out["ok"] is False
        assert out["image"] == ""

    def test_the_painter_names_itself(self, brain, frame):
        """"procedural" and "neural" are different pictures, and the wearer paid
        for the difference with a model file they supplied."""
        out = _look(brain, frame)
        assert out["painter"] == "procedural"
        assert out["neural"] is False

    def test_the_veil_blinds_the_dream_lens(self, brain, frame):
        brain.incognito_now = lambda: True
        out = _look(brain, frame)
        assert not out.get("image")
        assert out.get("ok") is not True


class TestTheModelPathIsSettable:

    def test_no_model_means_the_procedural_wash_not_a_failure(self, brain, frame):
        """Dream Mode works with nothing installed. That is the design, and the
        neural path is the upgrade — not the requirement."""
        assert brain.world_lens()._dream_model_path() == ""
        assert _look(brain, frame)["ok"] is True

    def test_the_config_path_is_read(self, brain, tmp_path):
        model = tmp_path / "style.onnx"
        model.write_bytes(b"not really a model, but a real file")
        brain.config.dream_model_path = str(model)
        assert brain.world_lens()._dream_model_path() == str(model)

    def test_the_environment_overrides_the_config(self, brain, tmp_path,
                                                  monkeypatch):
        """Matching `DL_DISABLE_*` / `disabled_caps` elsewhere: the env var is the
        ops-level override, the config field is the same switch made durable."""
        cfg_model = tmp_path / "cfg.onnx"
        env_model = tmp_path / "env.onnx"
        for p in (cfg_model, env_model):
            p.write_bytes(b"x")
        brain.config.dream_model_path = str(cfg_model)
        monkeypatch.setenv("DL_DREAM_MODEL", str(env_model))
        assert brain.world_lens()._dream_model_path() == str(env_model)

    def test_a_path_with_no_file_is_treated_as_unset(self, brain, tmp_path):
        """Passing it down would have `DreamStylizer` silently return None, so the
        wearer gets the wash and no clue their path is wrong."""
        brain.config.dream_model_path = str(tmp_path / "nope.onnx")
        assert brain.world_lens()._dream_model_path() == ""

    def test_a_directory_is_not_a_model(self, brain, tmp_path):
        brain.config.dream_model_path = str(tmp_path)
        assert brain.world_lens()._dream_model_path() == ""

    def test_whitespace_only_is_unset(self, brain):
        brain.config.dream_model_path = "   "
        assert brain.world_lens()._dream_model_path() == ""

    def test_the_path_round_trips_through_apply_config(self, brain, tmp_path):
        model = tmp_path / "style.onnx"
        model.write_bytes(b"x")
        brain.apply_config({"dream_model_path": str(model)})
        assert brain.config.dream_model_path == str(model)


class TestTheCapabilityIsPromotedOnlyByPROOF:

    def test_it_stays_declared_dormant_so_the_default_is_honest(self):
        from dreamlayer import capabilities as C
        assert "dream_style" in C._NOT_WIRED

    def test_a_procedural_look_never_promotes_it(self, brain, frame):
        """The wash is not the neural painter, however good it looks."""
        _look(brain, frame)
        assert brain.dream_neural_ready() is False
        assert getattr(brain, "_dream_neural_ok", False) is False

    def test_a_neural_painting_promotes_it(self, brain, frame, tmp_path,
                                           monkeypatch):
        """Forced rather than observed: onnxruntime and a real style model are not
        present in CI, and `assert promoted is onnxruntime_available` would be
        vacuous in exactly the environment that runs it."""
        model = tmp_path / "style.onnx"
        model.write_bytes(b"x")
        brain.config.dream_model_path = str(model)
        import dreamlayer.dream_mode.dream_style as DS

        class _Neural:
            kind = "neural"
            ready = True

            def stylize(self, f):
                import numpy as np
                return np.zeros((8, 8, 3), dtype="uint8")
        monkeypatch.setattr(DS, "default_stylizer", lambda p=None: _Neural())
        out = _look(brain, frame)
        assert out["neural"] is True and out["image"]
        assert brain.dream_neural_ready() is True

    def test_a_neural_painter_that_produces_nothing_does_not_promote_it(
            self, brain, frame, tmp_path, monkeypatch):
        """A session that loads can still fail on a frame. `ready` is the model;
        a picture is the proof."""
        model = tmp_path / "style.onnx"
        model.write_bytes(b"x")
        brain.config.dream_model_path = str(model)
        import dreamlayer.dream_mode.dream_style as DS

        class _Broken:
            kind = "neural"
            ready = True

            def stylize(self, f):
                return None
        monkeypatch.setattr(DS, "default_stylizer", lambda p=None: _Broken())
        _look(brain, frame)
        assert brain.dream_neural_ready() is False

    def test_removing_the_model_takes_it_back_down(self, brain):
        """Proof that it once worked is not a claim that it still can."""
        brain._dream_neural_ok = True
        brain.config.dream_model_path = ""
        assert brain.dream_neural_ready() is False

    def test_the_report_does_not_touch_the_environment(self, brain, tmp_path):
        """Computed into the report's own env copy. There is no start/stop event
        to hang a durable flag on, so one would go stale in both directions."""
        import os
        from dreamlayer.ai_brain.server.server import _capability_payload
        model = tmp_path / "style.onnx"
        model.write_bytes(b"x")
        brain.config.dream_model_path = str(model)
        brain._dream_neural_ok = True
        before = os.environ.get("DL_WIRED_DREAM_STYLE")
        assert _capability_payload(brain)["items"]
        assert os.environ.get("DL_WIRED_DREAM_STYLE") == before

    def test_the_flag_is_what_capabilities_reads_to_promote_it(self, monkeypatch):
        """The contract the report relies on, asserted directly.

        Going through `_capability_payload` and expecting "active" would be
        testing whether onnxruntime happens to be installed — it is not, in CI or
        here, so `installed()` short-circuits to "missing" long before the flag is
        consulted and the assertion would say nothing about promotion. Force the
        install check instead, so this measures the flag."""
        from dreamlayer import capabilities as C
        cap = C._BY_KEY["dream_style"]
        monkeypatch.setattr(C, "installed", lambda c: True)
        assert C.state(cap, env={}) == "dormant"
        assert C.state(cap, env={"DL_WIRED_DREAM_STYLE": "1"}) == "active"

    def test_the_report_does_not_promote_an_unproved_painter(self, brain,
                                                             tmp_path):
        from dreamlayer.ai_brain.server.server import _capability_payload
        model = tmp_path / "style.onnx"
        model.write_bytes(b"x")
        brain.config.dream_model_path = str(model)
        row = next(i for i in _capability_payload(brain)["items"]
                   if i["key"] == "dream_style")
        assert row["state"] != "active", row

    def test_a_missing_wheel_still_outranks_the_flag(self, brain, tmp_path):
        """Promotion cannot conjure a dependency. With onnxruntime absent the
        honest word is "missing", whatever the Brain proved earlier — and this is
        the state most installs are actually in."""
        pytest.importorskip  # noqa: B018 — documented below
        try:
            import onnxruntime  # noqa: F401
            pytest.skip("onnxruntime IS installed here")
        except ImportError:
            pass
        from dreamlayer.ai_brain.server.server import _capability_payload
        model = tmp_path / "style.onnx"
        model.write_bytes(b"x")
        brain.config.dream_model_path = str(model)
        brain._dream_neural_ok = True
        row = next(i for i in _capability_payload(brain)["items"]
                   if i["key"] == "dream_style")
        assert row["state"] == "missing", row

    def test_a_broken_dream_state_never_breaks_the_report(self, brain):
        from dreamlayer.ai_brain.server.server import _capability_payload

        def _boom():
            raise RuntimeError("no lens")
        brain.dream_neural_ready = _boom
        assert _capability_payload(brain)["items"]


class TestTheState:

    def test_it_distinguishes_set_from_found(self, brain, tmp_path):
        """The case worth surfacing: a path IS set, no file is there, and the
        wearer thinks the neural painter is on while getting the wash."""
        brain.config.dream_model_path = str(tmp_path / "gone.onnx")
        st = brain.dream_state()
        assert st["path"] and st["found"] is False

    def test_it_reports_an_environment_override(self, brain, tmp_path,
                                                monkeypatch):
        model = tmp_path / "s.onnx"
        model.write_bytes(b"x")
        monkeypatch.setenv("DL_DREAM_MODEL", str(model))
        assert brain.dream_state()["from_env"] is True

    def test_proved_and_active_are_separate_facts(self, brain, tmp_path):
        """They come apart the moment the model is removed."""
        model = tmp_path / "s.onnx"
        model.write_bytes(b"x")
        brain.config.dream_model_path = str(model)
        brain._dream_neural_ok = True
        assert brain.dream_state() == {
            "path": str(model), "found": True, "from_env": False,
            "proved": True, "active": True}
        model.unlink()
        st = brain.dream_state()
        assert st["proved"] is True and st["active"] is False


class TestItIsReachableFromBothSurfaces:

    def test_the_live_lens_has_a_dream_case_at_all(self):
        """It did not. A dream look fell to `default:` and drew "done"."""
        src = LIVE.read_text(encoding="utf-8")
        assert 'case "dream": glassDreamCard(j); break;' in src

    def test_the_live_lens_draws_the_returned_image(self):
        src = LIVE.read_text(encoding="utf-8")
        i = src.index("function glassDreamCard")
        body = src[i:i + 2200]
        assert "j.image" in body
        assert "drawImage" in body
        assert "data:image/jpeg;base64," in body

    def test_the_painting_is_drawn_before_the_card_is_scheduled_to_clear(self):
        """An Image decodes off-thread, so `gend` belongs inside onload — outside
        it the card is timed to clear from before it had drawn."""
        src = LIVE.read_text(encoding="utf-8")
        i = src.index("function glassDreamCard")
        body = src[i:src.index("function glassSkyCard")]
        onload = body.index("im.onload")
        assert body.index("gend(") > onload, "gend runs before the paint"
        assert body.index("drawImage") > onload

    def test_the_glass_names_which_painter_ran(self):
        src = LIVE.read_text(encoding="utf-8")
        i = src.index("function glassDreamCard")
        body = src[i:i + 2200]
        assert "NEURAL" in body and "PAINTERLY" in body

    def test_the_panel_can_set_the_model_path(self):
        src = PANEL.read_text(encoding="utf-8")
        assert 'id="dreamModel"' in src
        assert "async function saveDreamModel" in src
        i = src.index("async function saveDreamModel")
        assert "dream_model_path" in src[i:i + 400]

    def test_the_panel_says_when_the_path_does_not_resolve(self):
        """Saved-but-wrong is the failure a wearer cannot otherwise detect: the
        lens keeps working, with the wash."""
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function refreshDream")
        body = src[i:i + 1400]
        assert "j.found" in body
        assert "no file" in body or "has no file" in body

    def test_the_panel_loads_the_saved_path_back(self):
        src = PANEL.read_text(encoding="utf-8")
        assert '$("dreamModel").value=c.config.dream_model_path' in src

    def test_the_route_is_registered(self):
        from dreamlayer.ai_brain.server import server as S
        src = pathlib.Path(S.__file__).read_text(encoding="utf-8")
        assert '"/dreamlayer/dream": _get_dream' in src

    def test_the_csp_permits_a_data_uri_image(self):
        """The painting arrives as a data: URI; a CSP pinning img-src to 'self'
        would block it and the glass would stay blank with no error a wearer could
        act on. Asserted against the CONSTANT, not the source text — the first
        "img-src" in this file is in a comment about the policy, so scraping found
        the prose and not the rule."""
        from dreamlayer.ai_brain.server.server import PANEL_CSP
        directive = next(d.strip() for d in PANEL_CSP.split(";")
                         if d.strip().startswith("img-src"))
        assert "data:" in directive, directive
