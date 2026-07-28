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

import numpy as np
import pytest

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server import face_live
from dreamlayer.ai_brain.server.store import BrainConfig


def _frame(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)


def _brain(tmp_path, *, face: bool = True) -> Brain:
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    BrainConfig(token="tok", face_recognition=face).save(cfg)
    return Brain(cfg)


class TestTheShippedBuildStillCannotIdentifyAnyone:
    """The site's hardest promise, unchanged by wiring a model behind an extra."""

    @pytest.mark.no_face_double
    def test_the_production_embedder_declines_without_the_pack(self):
        from dreamlayer.truth_lens.face_backends import available
        from dreamlayer.truth_lens.face_embed import FaceEmbedder

        if available():
            pytest.skip("this install has the opt-in face pack AND its weights")
        emb = FaceEmbedder()
        assert emb.available is False, (
            "a default install reports a face embedder — the `face` extra is "
            "supposed to be opt-in and in no deployment profile")
        for seed in range(5):
            assert emb.process_frame(_frame(seed)) is None

    @pytest.mark.no_face_double
    def test_the_default_embed_fn_is_none_without_the_pack(self):
        from dreamlayer.truth_lens import face_backends

        if face_backends.available():
            pytest.skip("this install has the opt-in face pack AND its weights")
        assert face_backends.default_face_embed_fn() is None

    @pytest.mark.no_face_double
    def test_a_missing_weights_dir_is_not_an_error(self, tmp_path, monkeypatch):
        """The pack installed but the weights absent must decline, not raise —
        that is the state a user lands in between `pip install` and the model
        fetch."""
        from dreamlayer.truth_lens import face_backends

        monkeypatch.setenv("DL_FACE_MODEL_DIR", str(tmp_path / "nope"))
        face_backends.reset_cache()
        assert face_backends.available() is False
        assert face_backends.default_face_embed_fn() is None


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
