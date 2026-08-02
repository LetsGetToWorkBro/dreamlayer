"""PR2 intelligence-seam tests — verify every adapter's FALLBACK path (deps
optional and absent in CI). Adapters must not change host behaviour.
"""
from __future__ import annotations


# --- truth_lens: the AU channel is off BY DESIGN; prosody stands alone -------
def test_the_micro_expression_channel_stays_off():
    """RETIRED, inverted — `au_backends` was removed on 2026-08-02.

    This used to assert that four AU backends (LibreFace, py-feat, FaceTorch,
    OpenFace3) passed frames through untouched with no dependency installed.
    They did. The problem was what installing one would have DONE.

    The reworked Truth Lens turns the micro-expression channel off deliberately:
    `fusion.AU_CHANNEL_REAL` is False, its weight is 0.0, it is excluded from
    the confidence count, and it draws as an honest empty slot on the Testimony
    Thread. `truth_live.py` states the reason plainly — it "is the difference
    between a delivery read and a lie detector: this surface never claims to
    have seen a face twitch, because it has not."

    A capability whose only effect is to switch on a channel the design refuses
    is not a dormant capability, it is a loaded gun in the catalogue. So the
    adapters are gone and this asserts the refusal instead.

    `au_detector.py` is untouched and stays: it is what draws the empty slot.
    """
    import importlib.util
    assert importlib.util.find_spec(
        "dreamlayer.truth_lens.au_backends") is None, (
        "au_backends is back — see decisions/0007 for why it was retired")
    from dreamlayer.truth_lens.fusion import AU_CHANNEL_REAL, CHANNEL_WEIGHTS
    assert AU_CHANNEL_REAL is False
    assert CHANNEL_WEIGHTS["micro_expression"] == 0.0


def test_prosody_needs_no_dependency_at_all():
    """`causal_fusion` used to be asserted here too. It was dropped
    (decisions/0006): it imported dowhy purely as a flag, never called it, and
    read three attributes the credibility channels do not have — so it returned
    None whether or not the dependency was installed.

    `prosody_whisperx` joined it on 2026-08-02, for a different reason worth
    keeping. It was never broken: `word_timings()` returned [] without whisperx
    and real word timings with it. It was REDUNDANT. The reworked Truth Lens
    (`ai_brain/server/truth_live.py`) computes its voice-stress channel — pitch,
    jitter, shimmer, hesitation, pause ratio, speech rate — from
    `truth_lens/prosody.py` over the FFT frames the interpreter already
    produces, with no dependency. whisperx sharpened a channel that already
    works, for ~70 packages including torch and the CUDA 12 stack.

    So the assertion is inverted: the prosody channel must keep standing on its
    own, and a re-added optional dependency must not become the thing it needs.
    """
    import importlib.util
    assert importlib.util.find_spec(
        "dreamlayer.truth_lens.prosody_whisperx") is None, (
        "prosody_whisperx is back; if that is deliberate, decisions/0007 says "
        "why it was retired and what would have to change")
    from dreamlayer.truth_lens.prosody import ProsodyAnalyzer
    assert ProsodyAnalyzer() is not None


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


def test_the_hud_has_no_python_skia_renderer():
    """RETIRED, inverted — `hud/render_skia.py` was removed on 2026-08-02.

    It was a working Skia rasterizer sketch that could never reach a wearer.
    There are three renderers in this product and Skia only touched the one
    nobody wears:

      * `halo-lua/display/renderer.lua` — Lua, ON THE GLASSES;
      * the JS canvas in `ai_brain/server/live.py` — the Live Lens on the phone;
      * `hud/renderer.CardRenderer` — Python, the only thing Skia plugged into,
        and consumed solely by `hud/golden_images.py`, `hud/export.py` and
        `sdk/preview.py`. `grep CardRenderer ai_brain/` is empty: the Brain
        never renders a card in Python.

    So finishing it — drawing every card layout in Skia AND adding a whole-image
    renderer slot `CardRenderer` does not have — would have bought crisper
    golden-test images and a nicer SDK preview, for a capability the catalogue
    itself scored `impact=1`.
    """
    import importlib.util
    assert importlib.util.find_spec("dreamlayer.hud.render_skia") is None, (
        "render_skia is back — see decisions/0007 for why it was retired")
    from dreamlayer.hud.renderer import CardRenderer
    assert CardRenderer() is not None, "the PIL renderer is the one that stayed"
