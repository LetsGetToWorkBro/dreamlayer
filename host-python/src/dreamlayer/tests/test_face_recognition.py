"""test_face_recognition.py — recognising contacts, and refusing everyone else.

Two things are being proved here, and the second matters more than the first.

**That it works:** a face the wearer enrolled is recognised on the next look,
through a real `Brain(cfg)` — the wiring that did not exist before, because
`SocialLens` is built only on the `Orchestrator` the shipped Brain never
instantiates.

**That it stays silent otherwise**, which is the part a green suite could
otherwise lie about:

  * the SHIPPED default (no `face` pack, no weights) still declines every
    frame — the sentence on the website depends on it;
  * a face that matches nobody produces no stored template, no ledger line, and
    nothing in the logs — the "discarded immediately" promise, checked against
    the file on disk and the captured log records rather than asserted in prose;
  * ambient recognition is refused in a release build even with its env switch
    explicitly on.

The frames here are noise, not faces. The autouse test double
(`conftest._face_embedder_double`) makes `FaceEmbedder` match byte-identical
frames and nothing else, which is exactly the property these tests need: it
exercises every branch of the enrol/identify/discard path without pretending
anything can recognise a person across two photographs. Tests that must see the
PRODUCTION embedder opt out with `no_face_double`.
"""
from __future__ import annotations

import json
import logging
import time

import numpy as np
import pytest

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server import face_live
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.truth_lens import face_backends as _fb

# Captured at import, BEFORE conftest's fixture stubs the resolution for
# `no_face_double` tests. Tests that probe the BACKEND's own dependency/weights
# logic call these, so they exercise the real function rather than the stub and
# cannot pass vacuously.
_REAL_AVAILABLE = _fb.available
_REAL_DEFAULT_FN = _fb.default_face_embed_fn


def _frame(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)


def _brain(tmp_path, *, face: bool = True, consent: bool = True,
           auto: bool = False) -> Brain:
    """A Brain with face recall usable. Consent defaults to ACCEPTED because
    most tests here are about the capability, not the gate — the gate has its
    own tests below, and they set consent=False deliberately."""
    from dreamlayer.ai_brain.server.face_live import CONSENT_VERSION
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    BrainConfig(token="tok", face_recognition=face, face_auto_enrol=auto,
                face_consent_version=CONSENT_VERSION if consent else "").save(cfg)
    return Brain(cfg)


class TestTheShippedBuildStillCannotIdentifyAnyone:
    """The site's hardest promise, unchanged by wiring a model behind an extra."""

    @pytest.mark.no_face_double
    def test_the_production_embedder_declines_in_the_default_build(self):
        """The default build has no face pack, so the embedder declines. The
        precondition is guaranteed by conftest rather than by what happens to be
        installed on the machine running this — otherwise a developer who opted
        into the pack would silently flip the assertion."""
        from dreamlayer.truth_lens.face_embed import FaceEmbedder

        emb = FaceEmbedder()
        assert emb.available is False, (
            "a default install reports a face embedder — the `face` extra is "
            "supposed to be opt-in and in no deployment profile")
        for seed in range(5):
            assert emb.process_frame(_frame(seed)) is None

    @pytest.mark.no_face_double
    def test_the_real_resolver_returns_none_without_weights(self, tmp_path,
                                                            monkeypatch):
        """The REAL resolver (not conftest's stub), pointed at a directory with
        no weights: it must produce no embedder rather than raise or guess."""
        monkeypatch.setenv("DL_FACE_MODEL_DIR", str(tmp_path / "absent"))
        _fb.reset_cache()
        assert _REAL_AVAILABLE() is False
        assert _REAL_DEFAULT_FN() is None

    @pytest.mark.no_face_double
    def test_a_missing_weights_dir_is_not_an_error(self, tmp_path, monkeypatch):
        """The pack installed but the weights absent must decline, not raise —
        that is the state a user lands in between `pip install` and the model
        fetch."""

        monkeypatch.setenv("DL_FACE_MODEL_DIR", str(tmp_path / "nope"))
        _fb.reset_cache()
        assert _REAL_AVAILABLE() is False
        assert _REAL_DEFAULT_FN() is None


class TestTheSeamResolvesARealBackend:
    """`FaceEmbedder` must actually pick the backend up — the wiring, tested
    without needing a 300 MB model in CI."""

    @pytest.mark.no_face_double
    def test_a_wired_backend_becomes_available_and_answers(self, monkeypatch):
        from dreamlayer.truth_lens import face_embed as fe

        vec = [0.0] * 512
        vec[0] = 1.0
        import dreamlayer.truth_lens.face_backends as fb
        monkeypatch.setattr(fb, "default_face_embed_fn",
                            lambda: (lambda frame: (vec, 0.9)))

        emb = fe.FaceEmbedder()
        assert emb.available is True, "the seam did not resolve the backend"
        au = emb.process_frame(_frame(1))
        assert au is not None and len(au.embedding) == 512

    @pytest.mark.no_face_double
    def test_the_backend_is_resolved_once_not_per_frame(self, monkeypatch):
        """Resolution is cached: `FaceEmbedder` is constructed inside
        `SocialLens.__init__`, so a per-frame model probe would put the load
        cost on every frame."""
        import dreamlayer.truth_lens.face_backends as fb
        from dreamlayer.truth_lens.face_embed import FaceEmbedder

        calls = {"n": 0}

        def _factory():
            calls["n"] += 1
            return lambda frame: ([1.0] + [0.0] * 511, 0.9)

        monkeypatch.setattr(fb, "default_face_embed_fn", _factory)
        emb = FaceEmbedder()
        for seed in range(4):
            emb.process_frame(_frame(seed))
        assert emb.available is True
        assert calls["n"] == 1, f"backend resolved {calls['n']}× — expected once"


class TestRecognisingSomeoneYouIntroduced:
    """The capability itself, end to end through a real Brain."""

    def test_an_enrolled_face_is_recognised_on_the_next_look(self, tmp_path):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        face = _frame(7)

        assert fr.enrol("Ana", face)["ok"] is True

        seen = fr.identify(face)
        assert seen["known"] is True
        assert seen["name"] == "Ana"
        assert seen["confidence"] >= 0.65

    def test_enrolment_survives_a_restart(self, tmp_path):
        brain = _brain(tmp_path)
        face = _frame(8)
        brain.face_recall().enrol("Bo", face)

        again = Brain(tmp_path / "cfg")            # a fresh Brain, same cfg dir
        assert again.face_recall().identify(face)["name"] == "Bo"

    def test_someone_you_never_introduced_is_not_named(self, tmp_path):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))

        stranger = fr.identify(_frame(99))
        assert stranger["known"] is False
        assert stranger.get("reason") == "no-match"
        assert "name" not in stranger, "a non-match carried a name back"


class TestTheTemplateOfSomeoneWhoDidNotConsent:
    """The promise that makes the whole feature defensible."""

    def test_a_non_matching_template_is_never_written_to_disk(self, tmp_path):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))
        before = fr.path.read_bytes()

        for seed in (101, 102, 103):
            assert fr.identify(_frame(seed))["known"] is False

        assert fr.path.read_bytes() == before, (
            "the face index changed after identifying people who match nobody "
            "— a bystander's template was persisted")
        rows = json.loads(fr.path.read_text())
        assert [r["name"] for r in rows] == ["Ana"]

    def test_a_non_matching_template_is_never_logged(self, tmp_path, caplog):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))

        stranger = _frame(202)
        # the template this frame WOULD produce — nothing may echo its numbers
        au = fr._get_embedder().process_frame(stranger)
        assert au is not None
        needles = [f"{float(x):.6f}"[:8] for x in au.embedding[:8]]

        with caplog.at_level(logging.DEBUG, logger="dreamlayer"):
            assert fr.identify(stranger)["known"] is False
        blob = "\n".join(r.getMessage() for r in caplog.records)
        for n in needles:
            assert n not in blob, (
                "a face template component appeared in a log record — a "
                "biometric identifier in a text file")

    def test_a_non_matching_face_leaves_no_ledger_line(self, tmp_path):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))
        before = len(brain.activity.recent(200))

        fr.identify(_frame(303))

        assert len(brain.activity.recent(200)) == before, (
            "identifying a stranger wrote to the activity ledger — the record "
            "that they were looked at is itself a record about them")

    def test_no_template_is_computed_when_nobody_is_enrolled(self, tmp_path):
        """With an empty index the answer cannot be yes, so the model must not
        run at all — the cheapest possible respect for a bystander."""
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        calls = {"n": 0}
        real = fr._get_embedder().process_frame

        def _spy(frame):
            calls["n"] += 1
            return real(frame)

        fr._get_embedder().process_frame = _spy      # type: ignore[method-assign]
        out = fr.identify(_frame(5))
        assert out == {"known": False, "reason": "nobody-enrolled"}
        assert calls["n"] == 0, "a template was computed with nobody enrolled"


class TestTheFourLocks:
    def test_off_on_a_fresh_install(self):
        assert BrainConfig().face_recognition is False, (
            "face recognition ships ON — it must be an explicit opt-in")

    def test_the_switch_off_means_no_answer_and_no_template(self, tmp_path):
        brain = _brain(tmp_path, face=True)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))

        brain.config.face_recognition = False
        assert fr.identify(_frame(7)) == {"known": False, "reason": "off"}

    def test_the_veil_closes_the_camera(self, tmp_path, monkeypatch):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))

        monkeypatch.setattr(Brain, "incognito_now", lambda self: True)
        assert fr.identify(_frame(7)) == {"known": False, "reason": "veiled"}
        assert fr.enrol("Cy", _frame(9))["ok"] is False

    def test_an_unreadable_posture_fails_closed(self, tmp_path, monkeypatch):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))

        def _boom(self):
            raise RuntimeError("posture unreadable")

        monkeypatch.setattr(Brain, "incognito_now", _boom)
        assert fr.identify(_frame(7))["reason"] == "veiled", (
            "an unreadable trust signal resolved to 'look' rather than 'veiled'")

    def test_no_model_means_enrolment_refuses_rather_than_storing_nothing(
            self, tmp_path, monkeypatch):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        monkeypatch.setattr(type(fr), "model_available",
                            property(lambda self: False))
        out = fr.enrol("Ana", _frame(7))
        assert out["ok"] is False and "no face model" in out["error"]
        assert not fr.path.exists()


class TestAmbient:
    """A testing default that silently becomes the ship default is the bug class
    this codebase keeps producing. These are the two switches, kept apart."""

    def test_ambient_is_off_unless_explicitly_set(self, monkeypatch):
        monkeypatch.delenv(face_live.AMBIENT_ENV, raising=False)
        assert face_live.ambient_allowed() is False

    def test_ambient_can_be_turned_on_for_testing_on_a_source_build(
            self, monkeypatch):
        monkeypatch.delattr("sys.frozen", raising=False)
        monkeypatch.setenv(face_live.AMBIENT_ENV, "1")
        assert face_live.ambient_allowed() is True

    def test_a_release_build_refuses_ambient_even_with_the_flag_on(
            self, monkeypatch):
        """The promise. A frozen bundle cannot be talked into ambient
        recognition by an env var in a plist or a launch agent."""
        monkeypatch.setenv(face_live.AMBIENT_ENV, "1")
        monkeypatch.setattr("sys.frozen", "macosx_app", raising=False)
        assert face_live.ambient_allowed() is False

    def test_ambient_is_not_a_config_field(self):
        """Kept out of BrainConfig on purpose: a panel toggle is a thing a
        release build ships with, and this must not be."""
        assert not hasattr(BrainConfig(), "face_ambient")
        assert "face_ambient" not in json.dumps(BrainConfig().public())


class TestForgetting:
    def test_forgetting_one_contact_drops_their_face(self, tmp_path):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        face = _frame(11)
        cid = fr.enrol("Ana", face)["contact_id"]

        assert fr.forget(cid)["removed"] is True
        assert fr.identify(face)["known"] is False

    def test_erase_everything_reaches_the_face_index(self, tmp_path):
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        face = _frame(12)
        fr.enrol("Ana", face)
        assert fr.path.exists()

        out = brain.purge_memories()

        assert out["ok"] is True
        assert out["faces_purged"] == 1
        assert not fr.path.exists(), (
            "erase-everything left the enrolled face templates on disk — the "
            "most personal store on the device survived the wipe")
        assert brain.face_recall().identify(face)["known"] is False


# --------------------------------------------------------------------------
# The REAL model. Marked `real_model`, so it runs in the weekly real-models job
# (which installs the backend and FAILS if a marked test skips) and is
# deselected from the default gate, which must stay green with zero extras.
# --------------------------------------------------------------------------

@pytest.mark.real_model
@pytest.mark.no_face_double
class TestTheRealArcFaceBackend:
    """Against the actual buffalo_l weights, not a double.

    What these pin is the DECLINE direction, and that is deliberate. The
    predecessor stub's documented failure was that `mean(abs(frame))` asserted a
    face at 100% in any non-black image, so "the real detector says no to things
    that are not faces" is the exact regression worth holding — and it is
    checkable without shipping photographs of real people in the repo.

    Cross-photo recall ACCURACY is not tested here and cannot be: this repo
    contains no face photographs, and adding some would mean committing
    biometrics of real people to a public git history to test a privacy
    feature. `social_lens/index.py` already says the 0.65 threshold and 0.08
    margin are placeholders "until the real embedder is calibrated on-device
    (Rig 3 perception bench: set them from an ROC over genuine/impostor
    pairs)". That calibration is where accuracy gets established; this is not a
    substitute for it, and the thresholds should not be treated as validated
    until it has run.
    """

    def _fn(self):
        from dreamlayer.truth_lens import face_backends as fb
        fb.reset_cache()
        if not fb.available():
            pytest.skip("buffalo_l weights are not installed on this machine")
        fn = fb.default_face_embed_fn()
        assert fn is not None, (
            "the weights are present but no embed_fn was produced — the model "
            "failed to load; check the model_guard verification path, which has "
            "silently refused a perfectly good install before")
        return fn

    def test_the_pack_being_present_makes_the_embedder_available(self):
        from dreamlayer.truth_lens.face_embed import FaceEmbedder
        self._fn()
        assert FaceEmbedder().available is True

    def test_the_real_detector_declines_noise(self):
        """The stub's exact bug, against the real model: random pixels are not
        a face, and must not produce a template."""
        fn = self._fn()
        for seed in range(4):
            rng = np.random.default_rng(seed)
            frame = rng.integers(0, 255, (256, 256, 3), dtype=np.uint8)
            assert fn(frame) is None, (
                "the real detector returned a face template for uniform noise")

    def test_the_real_detector_declines_flat_and_empty_frames(self):
        fn = self._fn()
        assert fn(np.zeros((256, 256, 3), dtype=np.uint8)) is None
        assert fn(np.full((256, 256, 3), 255, dtype=np.uint8)) is None
        assert fn(np.zeros((0, 0, 3), dtype=np.uint8)) is None

    def test_a_non_colour_frame_is_declined_not_crashed(self):
        fn = self._fn()
        assert fn(np.zeros((64, 64), dtype=np.uint8)) is None
        assert fn(None) is None

    def test_unpinned_weights_warn_but_still_load(self):
        """models.lock ships this entry unpinned, as every model in it is. That
        must warn, not disable the feature: reading `verify_path`'s False as a
        refusal made face recall silently unavailable on a machine with the
        model correctly installed."""
        from dreamlayer.truth_lens import face_backends as fb
        self._fn()
        assert fb._verify_weights(fb.model_root()) is True

    def test_tampered_weights_refuse_to_load(self, monkeypatch):
        """The fatal case. A hash MISMATCH must stop the load — for weights that
        decide who the wearer is looking at, a wrong file is never tolerated."""
        from dreamlayer import model_guard
        from dreamlayer.truth_lens import face_backends as fb
        self._fn()

        def _boom(*a, **kw):
            raise model_guard.ModelIntegrityError("sha256 mismatch")

        monkeypatch.setattr(model_guard, "verify_path", _boom)
        assert fb._verify_weights(fb.model_root()) is False
        fb.reset_cache()
        assert fb.default_face_embed_fn() is None or fb._get_app() is None


@pytest.mark.real_model
@pytest.mark.no_face_double
def test_importing_the_face_backend_does_not_phone_home():
    """`insightface` pulls in `albumentations`, which runs an update check
    against a public host on import. On an on-device/LAN-only product a
    transitive dependency opening an HTTPS connection because it was imported is
    a privacy regression whatever it sends — this repo's own egress harness
    caught it the moment insightface entered the tree. The opt-out is read at
    IMPORT time, so it has to be set before the import, not at Brain start-up."""
    import os
    from dreamlayer.truth_lens import face_backends as fb

    fb._deps_present()
    assert os.environ.get("NO_ALBUMENTATIONS_UPDATE") == "1", (
        "the albumentations update check is not disabled — importing the face "
        "backend reaches a public host")


class TestTheHttpSurface:
    """The routes the phone actually calls. A capability with no route is the
    bug this whole change exists to fix, one layer up — so the wiring is tested
    over a real server, not by calling the methods directly."""

    @staticmethod
    def _live(tmp_path, token="tok"):
        import json as _json
        import threading
        import urllib.request
        from dreamlayer.ai_brain.server import make_brain_server

        cfg = tmp_path / "cfg"
        cfg.mkdir(exist_ok=True)
        from dreamlayer.ai_brain.server.face_live import CONSENT_VERSION
        BrainConfig(token=token, face_recognition=True,
                    face_consent_version=CONSENT_VERSION).save(cfg)
        brain = Brain(cfg)
        srv = make_brain_server(brain, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        headers = {"X-DreamLayer-Token": token,
                   "Content-Type": "application/json"}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def call(path, body=None):
            req = urllib.request.Request(
                url + path, headers=headers,
                data=None if body is None else _json.dumps(body).encode())
            return _json.loads(opener.open(req, timeout=5).read())

        return brain, srv, call

    @staticmethod
    def _b64(frame) -> str:
        import base64
        import io

        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(frame).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def test_enrol_then_identify_over_http(self, tmp_path):
        pytest.importorskip("PIL")
        brain, srv, call = self._live(tmp_path)
        try:
            img = self._b64(_frame(21))
            out = call("/dreamlayer/face/enrol", {"name": "Ana", "image": img})
            assert out["ok"] is True, out

            seen = call("/dreamlayer/face/identify", {"image": img})
            assert seen["known"] is True and seen["name"] == "Ana"

            stranger = call("/dreamlayer/face/identify",
                            {"image": self._b64(_frame(22))})
            assert stranger["known"] is False
            assert "name" not in stranger
        finally:
            srv.shutdown(); srv.server_close()

    def test_the_identify_response_carries_no_biometrics(self, tmp_path):
        """Whatever the answer, the wire must not carry a template or the
        geometry of a face — least of all for someone who matched nobody."""
        pytest.importorskip("PIL")
        brain, srv, call = self._live(tmp_path)
        try:
            call("/dreamlayer/face/enrol",
                 {"name": "Ana", "image": self._b64(_frame(23))})
            for seed in (23, 24):
                body = call("/dreamlayer/face/identify",
                            {"image": self._b64(_frame(seed))})
                assert not (set(body) & {"embedding", "template", "vector",
                                         "bbox", "landmarks", "crop"}), body
        finally:
            srv.shutdown(); srv.server_close()

    def test_the_status_route_reports_capability_not_content(self, tmp_path):
        pytest.importorskip("PIL")
        brain, srv, call = self._live(tmp_path)
        try:
            call("/dreamlayer/face/enrol",
                 {"name": "Ana", "image": self._b64(_frame(25))})
            st = call("/dreamlayer/face")
            assert st["enrolled"] == 1
            # The rule is CONTENT, not shape: the route may grow capability and
            # count fields (it has — consent state, auto-enrol, unnamed count),
            # but never anything about a specific person. Pinning the exact key
            # set made honest additions look like regressions.
            assert "Ana" not in json.dumps(st), "a name reached the status route"
            assert not (set(st) & {"embedding", "template", "vector", "bbox",
                                   "landmarks", "crop", "contacts", "names"})
            for value in st.values():               # no nested content either
                assert not isinstance(value, (list, dict)) or not value, (
                    f"status carried a collection: {value!r}")
        finally:
            srv.shutdown(); srv.server_close()

    def test_forget_over_http(self, tmp_path):
        pytest.importorskip("PIL")
        brain, srv, call = self._live(tmp_path)
        try:
            img = self._b64(_frame(26))
            cid = call("/dreamlayer/face/enrol",
                       {"name": "Ana", "image": img})["contact_id"]
            assert call("/dreamlayer/face/forget",
                        {"contact_id": cid})["removed"] is True
            assert call("/dreamlayer/face/identify",
                        {"image": img})["known"] is False
        finally:
            srv.shutdown(); srv.server_close()

    def test_the_routes_are_token_gated(self, tmp_path):
        """An unauthenticated caller must not be able to ask who is in a frame."""
        import urllib.error
        import urllib.request

        pytest.importorskip("PIL")
        brain, srv, _ = self._live(tmp_path)
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}"
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}))
            req = urllib.request.Request(
                url + "/dreamlayer/face/identify", data=b"{}",
                headers={"Content-Type": "application/json"})
            with pytest.raises(urllib.error.HTTPError) as err:
                opener.open(req, timeout=5)
            assert err.value.code in (401, 403)
        finally:
            srv.shutdown(); srv.server_close()


# --------------------------------------------------------------------------
# In-app consent, and auto-enrol — the wearer's accepted risk.
#
# The owner reversed the earlier "verbal consent, no UI" position: consent is
# now in-app and versioned, and auto-enrol stores a template for EVERY face
# seen, bystanders included. These pin what that does and does not change. What
# it does NOT change: the Veil still closes the camera, erase still reaches
# every stored face, and the wearer's switch still has to be on.
# --------------------------------------------------------------------------

class TestConsentIsRequired:
    def test_a_fresh_install_has_not_consented(self):
        assert BrainConfig().face_consent_version == ""
        assert BrainConfig().face_auto_enrol is False

    def test_without_consent_nothing_runs(self, tmp_path):
        from dreamlayer.ai_brain.server.face_live import CONSENT_VERSION
        brain = _brain(tmp_path, consent=False)
        fr = brain.face_recall()
        out = fr.identify(_frame(3))
        assert out["known"] is False
        assert out["reason"] == "no-consent"
        assert out["consent_required"] == CONSENT_VERSION
        assert fr.enrol("Ana", _frame(3))["ok"] is False

    def test_accepting_consent_turns_it_on(self, tmp_path):
        brain = _brain(tmp_path, consent=False)
        fr = brain.face_recall()
        assert fr.consented is False
        assert fr.accept_consent()["ok"] is True
        assert fr.consented is True
        assert fr.enrol("Ana", _frame(4))["ok"] is True

    def test_a_stale_consent_version_does_not_count(self, tmp_path):
        """Agreeing to different words is not this agreement — changing the
        terms must re-prompt rather than inherit the old acceptance."""
        brain = _brain(tmp_path, consent=False)
        brain.config.face_consent_version = "2020-01-01.something.else"
        fr = brain.face_recall()
        assert fr.consented is False
        assert fr.identify(_frame(5))["reason"] == "no-consent"
        assert fr.accept_consent("2020-01-01.something.else")["ok"] is False

    def test_withdrawing_consent_stops_recall_without_deleting(self, tmp_path):
        """Withdrawal and erasure are separate deliberate acts."""
        brain = _brain(tmp_path)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(6))
        out = fr.revoke_consent()
        assert out["ok"] is True and out["still_stored"] == 1
        assert fr.identify(_frame(6))["reason"] == "no-consent"

    def test_the_consent_text_names_the_bystander_problem(self):
        """The wearer is accepting a risk on behalf of people who cannot accept
        it here. If the text ever stops saying so, this fails."""
        from dreamlayer.ai_brain.server.face_live import CONSENT_TEXT
        low = CONSENT_TEXT.lower()
        assert "biometric" in low
        assert "bystander" in low or "not agreed" in low
        assert "bipa" in low or "gdpr" in low


class TestAutoEnrol:
    def test_off_by_default_a_stranger_is_still_discarded(self, tmp_path):
        brain = _brain(tmp_path, auto=False)
        fr = brain.face_recall()
        fr.enrol("Ana", _frame(7))
        before = fr.path.read_bytes()
        assert fr.identify(_frame(70))["reason"] == "no-match"
        assert fr.path.read_bytes() == before

    def test_on_a_stranger_is_stored_and_recognised_next_time(self, tmp_path):
        brain = _brain(tmp_path, auto=True)
        fr = brain.face_recall()
        stranger = _frame(71)

        first = fr.identify(stranger)
        assert first["auto_enrolled"] is True
        assert first["unnamed"] is True
        assert first["name"] == ""

        again = fr.identify(stranger)
        assert again["known"] is True
        assert again["contact_id"] == first["contact_id"]
        assert again["seen_count"] == 2, "encounters are not being counted"

    def test_an_auto_enrolled_face_gets_no_fabricated_name(self, tmp_path):
        """A placeholder name reads like knowledge. Unnamed is honest."""
        fr = _brain(tmp_path, auto=True).face_recall()
        out = fr.identify(_frame(72))
        assert out["name"] == ""
        assert "person-" not in json.dumps(out)

    def test_naming_promotes_it_out_of_the_unnamed_sweep(self, tmp_path):
        fr = _brain(tmp_path, auto=True).face_recall()
        cid = fr.identify(_frame(73))["contact_id"]
        assert fr.name_identity(cid, "Bo")["ok"] is True
        assert fr.identify(_frame(73))["name"] == "Bo"
        # backdate it well past the window; a NAMED contact must survive
        fr._meta[cid]["last_ts"] = time.time() - 400 * 86400
        assert fr.sweep_unnamed(90.0) == 0
        assert fr.identify(_frame(73))["name"] == "Bo"

    def test_unnamed_strangers_age_out_on_the_warm_window(self, tmp_path):
        fr = _brain(tmp_path, auto=True).face_recall()
        cid = fr.identify(_frame(74))["contact_id"]
        fr._meta[cid]["last_ts"] = time.time() - 400 * 86400

        assert fr.sweep_unnamed(90.0) == 1, (
            "an unnamed stranger the camera saw once is kept forever — the "
            "store grows without bound with people the wearer cannot identify")
        assert fr.identify(_frame(74)).get("auto_enrolled") is True  # re-enrolled

    def test_a_hand_enrolled_contact_is_never_swept(self, tmp_path):
        fr = _brain(tmp_path, auto=True).face_recall()
        fr.enrol("Ana", _frame(75))
        assert fr.sweep_unnamed(0.001) == 0

    def test_auto_enrol_still_obeys_the_veil(self, tmp_path, monkeypatch):
        brain = _brain(tmp_path, auto=True)
        fr = brain.face_recall()
        monkeypatch.setattr(Brain, "incognito_now", lambda self: True)
        assert fr.identify(_frame(76))["reason"] == "veiled"
        assert not fr.path.exists(), "a face was stored while veiled"

    def test_auto_enrol_requires_consent_like_everything_else(self, tmp_path):
        fr = _brain(tmp_path, auto=True, consent=False).face_recall()
        assert fr.identify(_frame(77))["reason"] == "no-consent"
        assert not fr.path.exists()

    def test_erase_everything_still_reaches_auto_enrolled_faces(self, tmp_path):
        brain = _brain(tmp_path, auto=True)
        fr = brain.face_recall()
        fr.identify(_frame(78))
        assert fr.path.exists()
        assert brain.purge_memories()["faces_purged"] >= 1
        assert not fr.path.exists()

    def test_status_reports_how_many_are_unnamed(self, tmp_path):
        fr = _brain(tmp_path, auto=True).face_recall()
        fr.enrol("Ana", _frame(79))
        fr.identify(_frame(80))
        st = fr.status()
        assert st["auto_enrol"] is True
        assert st["consented"] is True
        assert st["enrolled"] == 2 and st["unnamed"] == 1
