"""PR2 intelligence-seam tests — verify every adapter's FALLBACK path (deps
optional and absent in CI). Adapters must not change host behaviour.
"""
from __future__ import annotations


# --- truth_lens: AU backends passthrough; prosody/causal degrade cleanly -----
def test_au_backends_passthrough():
    from dreamlayer.truth_lens.au_backends import LibreFaceAU, PyFeatAU, FaceTorchAU, OpenFace3AU
    sentinel = object()
    for B in (LibreFaceAU, PyFeatAU, FaceTorchAU, OpenFace3AU):
        assert B().process(sentinel) is sentinel   # passthrough with no dep
        assert B().process(None) is None


def test_prosody_and_causal_fallback():
    from dreamlayer.truth_lens.prosody_whisperx import WhisperXProsody
    from dreamlayer.truth_lens.causal_fusion import CausalFusion
    assert WhisperXProsody().word_timings("nope.wav") == []
    assert CausalFusion().assess() is None            # no dowhy → None


# --- orchestrator: ECAPA hash embed; commitment/taste/persona fallbacks ------
def test_ecapa_hash_embed():
    from dreamlayer.orchestrator.speaker_ecapa import ECAPASpeaker, DIM
    a = ECAPASpeaker().embed(None, key="marcus reyes")
    b = ECAPASpeaker().embed(None, key="marcus reyes")
    c = ECAPASpeaker().embed(None, key="priya anand")
    assert len(a) == DIM and a == b                    # deterministic
    assert ECAPASpeaker.similarity(a, b) > ECAPASpeaker.similarity(a, c)


def test_commitment_nlp_fallback():
    from dreamlayer.orchestrator.commitment_nlp import CommitmentNLP
    c = CommitmentNLP().extract("Send Marcus the lease by Friday")
    assert c is not None and c.deadline and "friday" in c.deadline.lower()
    assert c.subject == "Marcus"


def test_taste_river_fallback_learns():
    from dreamlayer.orchestrator.taste_river import RiverTasteRanker
    r = RiverTasteRanker()
    for _ in range(5):
        r.observe("oat-latte", True)
        r.observe("black-coffee", False)
    ranked = r.rerank([("black-coffee", 1), ("oat-latte", 2)])
    assert ranked[0][0] == "oat-latte"


def test_persona_humanlearn_default():
    from dreamlayer.orchestrator.persona_humanlearn import HumanLearnClassifier
    assert HumanLearnClassifier(default="calm").classify({"x": 1}) == "calm"
    assert HumanLearnClassifier(rule=lambda f: "busy").classify({}) == "busy"


# --- social_lens: NER heuristic; diarization single-speaker ------------------
def test_ner_and_diarize_fallback():
    from dreamlayer.social_lens.ner_spacy import SpacyNER
    from dreamlayer.social_lens.diarize_diart import DiartDiarizer
    assert "Priya" in SpacyNER().people("Hi I'm Priya from Overpass Studio")
    turns = DiartDiarizer().turns(b"\x00\x00")
    assert turns and turns[0]["speaker"] == "spk0"


# --- object_lens: classifiers return None so recognizer keeps its mock -------
def test_object_classifiers_fallback():
    from dreamlayer.object_lens.classify_backends import (
        ClipClassifier, YoloClassifier, MoondreamClassifier, CoreMLClassifier)
    for c in (ClipClassifier(["snake plant"]), YoloClassifier(), MoondreamClassifier(), CoreMLClassifier()):
        assert c(object()) is None


# --- dream_mode: river weather, EyeMU gestures, scene, tracker ---------------
def test_weather_river_fallback():
    from dreamlayer.dream_mode.weather_river import RiverWeather
    w = RiverWeather()
    w.update(1.0); w.update(0.0)
    assert 0.0 <= w.sample() <= 1.0


def test_eyemu_gestures():
    from dreamlayer.dream_mode.imu_eyemu import EyeMUGestures
    g = EyeMUGestures()
    assert g.detect({"pitch": 0.5}) == "confirm"
    assert g.detect({"tap": True}, now=1.0) is None
    assert g.detect({"tap": True}, now=1.2) == "repeat"     # double-tap within window


def test_scene_lostfound_and_tracker():
    from dreamlayer.dream_mode.scene_lostfound import LostFoundScene
    from dreamlayer.dream_mode.track_supervision import SupervisionTracker
    s = LostFoundScene()
    s.observe("keys", "kitchen counter", now=10.0)
    assert s.where("keys")["place"] == "kitchen counter"
    assert s.vision_fn(object()) is None
    t = SupervisionTracker()
    ids1 = t.update([(0.1, 0.1), (0.8, 0.8)])
    ids2 = t.update([(0.11, 0.09), (0.82, 0.79)])   # same objects, slight drift
    assert ids1 == ids2 and len(set(ids1)) == 2


# --- rem: spatial anchor + egolife temporal buckets --------------------------
def test_spatial_and_egolife():
    from dreamlayer.rem.spatial_anchor import SpatialMemory
    from dreamlayer.rem.egolife_index import EgoLifeIndex
    sm = SpatialMemory()
    sm.anchor("cafe-pine", {"summary": "cash only"})
    assert sm.recall("cafe-pine")[0]["summary"] == "cash only"
    ego = EgoLifeIndex()
    now = 1_000_000.0
    ego.add(now - 10, "note", "today thing")
    ego.add(now - EgoLifeIndex.DAY - 10, "note", "yesterday thing")
    buckets = ego.by_day(days=7, now=now)
    assert 0 in buckets and 1 in buckets
