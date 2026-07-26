"""Automatic lens selection on the live path: the glance arbiter decides the
lens from what's in view (fire the winner, offer a chooser when ambiguous)
instead of a manual dropdown. These tests pin the wiring — WorldLensHost.glance
+ the live candidate set + world_look routing — deterministically, with no
optional vision deps (the zero-model HeuristicPerceptor drives it)."""
from __future__ import annotations

import tempfile

import numpy as np
import pytest

from dreamlayer.ai_brain.server import live as live_mod
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.world_lens import build_world_lens
from dreamlayer.ai_brain.server import glance_live


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _flat_frame():
    return np.full((64, 64, 3), 120, np.uint8)     # low texture → object-ish


def _text_frame():
    f = np.zeros((64, 64, 3), np.uint8)            # high-gradient stripes → text-dense
    f[::2, :, :] = 255
    return f


# --- the arbiter is genuinely wired (not the None stub) ----------------------

def test_worldlenshost_builds_the_arbiter(brain):
    wl = build_world_lens(brain)
    assert wl.perception is not None
    assert wl.glance_arbiter is not None


def test_flat_frame_hands_back_to_the_object_floor(brain):
    wl = build_world_lens(brain)
    assert wl.glance(_flat_frame())["kind"] == "object"


def test_text_frame_offers_a_read_or_math_chooser(brain):
    wl = build_world_lens(brain)
    g = wl.glance(_text_frame())
    assert g["kind"] == "offer"
    assert g["scene"] == "text"
    card = g["card"]
    assert card["type"] == "GlanceChoiceCard"
    lenses = {o["lens"] for o in card["options"]}
    assert lenses == {"read", "math"}              # the two text lenses, no more


def test_incognito_veils_the_glance(brain):
    brain.config.network_mode = "lan_only"
    wl = build_world_lens(brain)
    assert wl.glance(_flat_frame())["kind"] == "veiled"


# --- world_look routes the glance decision -----------------------------------

def test_world_look_returns_the_chooser_on_ambiguous_text(brain):
    out = live_mod.world_look(brain, _text_frame())
    assert out["ok"] is True and out.get("glance") == "offer"
    assert out["card"]["type"] == "GlanceChoiceCard"


def test_world_look_object_frame_falls_to_recognition(brain):
    # a flat frame → arbiter abstains → the normal object path runs (no glance key)
    out = live_mod.world_look(brain, _flat_frame())
    assert "glance" not in out                     # took the object-recognition floor


def test_ambient_never_auto_glances(brain, monkeypatch):
    # a passive-loop frame must not run the arbiter (kept quiet + local)
    called = {"n": 0}
    real = build_world_lens(brain)

    def _spy(*a, **k):
        called["n"] += 1
        return {"kind": "object"}
    monkeypatch.setattr(real, "glance", _spy)
    monkeypatch.setattr(Brain, "world_lens", lambda self: real)
    live_mod.world_look(brain, _text_frame(), ambient=True)
    assert called["n"] == 0


# --- the learning loop: a chooser pick reinforces the arbiter -----------------

def test_choosing_a_lens_teaches_the_arbiter(brain):
    wl = build_world_lens(brain)
    before = wl.glance_arbiter.priors.boost("text", "math")
    # simulate the chooser tap: manual lens=math with the scene it was offered for
    live_mod.world_look(brain, _flat_frame(), lens="math", scene="text")
    after = brain.world_lens()                      # same cached host
    assert after.glance_arbiter.priors.boost("text", "math") > before


def test_reading_teaches_the_read_candidate_not_the_doc_key(brain):
    # the chooser runs the "doc" lens but the arbiter learns the "read" CANDIDATE
    # key — reinforcing "doc" would be a dead no-op (the read candidate never
    # gets boosted). Teaching must land on "read".
    wl = brain.world_lens()
    live_mod.world_look(brain, _flat_frame(), lens="doc", scene="text")
    assert wl.glance_arbiter.priors.boost("text", "read") > 0      # the candidate key
    assert wl.glance_arbiter.priors.boost("text", "doc") == 0      # NOT the run key


# --- the learning loop never writes under the veil / with junk scenes ---------

def test_veiled_chooser_pick_teaches_nothing(brain):
    # a chooser tap while the shield is up must persist NOTHING — the veil
    # writes nothing to disk, the arbiter's priors included.
    brain.config.network_mode = "lan_only"          # shield up (incognito)
    wl = brain.world_lens()
    before = wl.glance_arbiter.priors.boost("text", "math")
    live_mod.world_look(brain, _flat_frame(), lens="math", scene="text")
    assert wl.glance_arbiter.priors.boost("text", "math") == before


def test_reinforce_ignores_unknown_scene_keys():
    # a crafted/oversized scene can't become a top-level key (the file is
    # rewritten whole on every reinforce, so an unbounded key set is a disk DoS).
    from dreamlayer.orchestrator.glance import GlancePriors
    p = GlancePriors()
    p.reinforce("x" * 5000, "read")                 # junk scene → dropped
    assert "x" * 5000 not in p.to_dict()["counts"]
    p.reinforce("text", "read")                     # a real scene still lands
    assert p.to_dict()["counts"]["text"]["read"] > 0


def test_unknown_manual_lens_does_not_reinforce(brain):
    # only a lens the chooser can post (doc/math) may teach the arbiter; a
    # crafted ?lens=…&scene=… with any other lens key writes nothing.
    wl = brain.world_lens()
    live_mod.world_look(brain, _flat_frame(), lens="totally-made-up", scene="text")
    assert wl.glance_arbiter.priors.boost("text", "totally-made-up") == 0.0


# --- the live candidate set only bids lenses the host can run -----------------

def test_live_candidates_exclude_person_and_scholar():
    lenses = {c.lens for c in glance_live.LIVE_CANDIDATES}
    assert "person" not in lenses                  # faces defer to the Social Lens
    # depth/sky/segment joined in the Tier-1 perception pass — they were absent
    # because no scene cue could justify them, not as policy. `find` is still out:
    # it needs the nouns you're hunting, which no bare frame supplies.
    assert lenses <= {"taste", "rosetta", "read", "math", "juno",
                      "depth", "sky", "segment"}
    assert "find" not in lenses


# --- Tier 1: the arbiter can finally SEE (2026-07-23) -------------------------
# It was built to read ten signals and the live path fed it two, so every scene
# collapsed to "text" or "object" — shelf/menu/sky were unreachable and taste and
# translate could never bid. These pin the cues → scene → lens chain on synthetic
# frames, so a regression in the cue maths shows up as a wrong LENS, not a silent
# drift back to guessing.

def _act(frame, hints=None):
    """(scene, decision kind, fired action) for one frame + optional phone cues."""
    import numpy as np  # noqa: F401
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    from dreamlayer.orchestrator.glance import classify_coarse, GlanceContext
    from dreamlayer.ai_brain.server.glance_live import build_live_arbiter
    sig = HeuristicPerceptor().perceive(frame).as_signals()
    for k, v in (hints or {}).items():
        sig[k] = v
    reading = classify_coarse(sig, "en")
    d = build_live_arbiter(None).arbitrate(
        reading, GlanceContext(dwell_ms=400.0, veiled=False))
    w = getattr(d, "winner", None)
    return reading.scene, d.kind, (w.action if w else None)


def _page():
    import numpy as np
    rng = np.random.default_rng(3)
    a = np.full((240, 240), 225, np.uint8)
    for y in range(20, 220, 10):
        for x in range(20, 220, 6):
            if rng.random() > 0.25:
                a[y:y + 5, x:x + 4] = rng.integers(20, 70)
    return a


def _shelf():
    import numpy as np
    a = np.full((240, 240), 150, np.uint8)
    for x in range(15, 225, 26):
        a[70:180, x:x + 16] = 60
    return a


def _night_sky():
    import numpy as np
    rng = np.random.default_rng(11)
    a = np.full((240, 240), 8, np.uint8)
    for _ in range(12):
        y, x = rng.integers(5, 235, 2)
        a[y, x] = 250
    return a


def test_a_photographed_page_fires_read():
    scene, kind, action = _act(_page())
    assert scene == "text" and kind == "fire" and action == "read"


def test_a_shelf_of_items_fires_taste():
    """Impossible before Tier 1: nothing produced `items`/`shelf`, so TasteLens
    could never bid no matter what you pointed at."""
    scene, kind, action = _act(_shelf())
    assert scene == "shelf" and kind == "fire" and action == "taste"


def test_the_night_sky_fires_the_sky_lens():
    scene, kind, action = _act(_night_sky())
    assert scene == "sky" and kind == "fire" and action == "sky"


def test_a_lit_room_is_not_mistaken_for_the_sky():
    import numpy as np
    a = np.full((240, 240), 20, np.uint8)
    a[60:180, 60:180] = 200                 # one big bright area, not point lights
    assert _act(a)[0] != "sky"


def test_foreign_text_fires_translate():
    """Also impossible before: `language` was never produced on the live path."""
    scene, kind, action = _act(_page(), {"language": "fr"})
    assert scene == "foreign_text" and kind == "fire" and action == "translate"


def test_a_person_in_frame_never_fires_a_reading_lens():
    scene, _kind, action = _act(_page(), {"has_face": True})
    assert scene == "person"
    assert action not in ("read", "math", "taste")    # and never "person"


def test_the_phones_own_detections_reach_the_arbiter():
    from dreamlayer.ai_brain.server import live as live_mod
    cues = live_mod.parse_cues({"ndet": ["4"], "objs": ["bottle,bottle,cup"],
                                "face": ["1"]})
    assert cues["items"] == 4
    assert cues["shelf"] is True          # a repeated label IS several comparables
    assert cues["has_face"] is True
    assert "box" not in cues and "crop" not in cues


def test_client_cues_are_sanitised():
    from dreamlayer.ai_brain.server import live as live_mod
    hostile = {"ndet": ["not-a-number"], "objs": ["<script>alert(1)</script>,../../etc"]}
    cues = live_mod.parse_cues(hostile)
    assert "items" not in cues
    for label in cues.get("objs", []):
        assert label.replace(" ", "").isalpha()
    assert live_mod.parse_cues({}) == {}
    assert live_mod.parse_cues({"ndet": ["999999"]})["items"] <= 24


# --- Tiers 2-4: posture, spoken intent, and learning -------------------------

def _fresh(frame, **ctxkw):
    """A FRESH arbiter per call: the shared one deliberately holds a decision for
    a debounce window (hysteresis), which would mask a changed bid."""
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    from dreamlayer.orchestrator.glance import classify_coarse, GlanceContext
    from dreamlayer.ai_brain.server.glance_live import build_live_arbiter
    sig = HeuristicPerceptor().perceive(frame).as_signals()
    for k in list(ctxkw.get("signals", {})):
        sig[k] = ctxkw["signals"][k]
    ctxkw.pop("signals", None)
    reading = classify_coarse(sig, "en")
    d = build_live_arbiter(None).arbitrate(
        reading, GlanceContext(veiled=False, **ctxkw))
    return d, getattr(d, "winner", None)


# Tier 2 — where the head is pointed

def test_tipping_the_head_down_over_text_strengthens_read():
    _d, level = _fresh(_page())
    _d2, down = _fresh(_page(), tilt_deg=-35.0)
    assert level.action == down.action == "read"
    assert down.salience > level.salience
    assert "in your hands" in down.reason


def test_looking_up_at_night_reaches_the_sky_even_when_the_pixels_are_unsure():
    import numpy as np
    flat_dark = np.full((240, 240), 10, np.uint8)      # no point lights at all
    _d, none_level = _fresh(flat_dark, tilt_deg=0.0, hour=12)
    _d2, up_night = _fresh(flat_dark, tilt_deg=45.0, hour=23)
    assert none_level is None                          # noon, level → not the sky
    assert up_night is not None and up_night.action == "sky"


def test_the_daypart_vocabulary_is_fixed():
    from dreamlayer.orchestrator.glance import daypart, DAYPARTS
    assert daypart(8) == "morning" and daypart(14) == "afternoon"
    assert daypart(20) == "evening" and daypart(2) == "night"
    assert all(daypart(h) in DAYPARTS for h in range(-48, 72))


# Tier 3 — what you said IS the intent

def test_spoken_intent_maps_speech_to_the_right_lens():
    from dreamlayer.ai_brain.server.spoken_intent import parse_spoken_intent as P
    assert P("where did I leave my keys")["intent"] == "find"
    assert P("where did I leave my keys")["terms"] == ["keys"]
    assert P("find my inhaler")["terms"] == ["inhaler"]
    assert P("what does this say")["intent"] == "read"
    assert P("what does this say")["lens"] == "doc"      # candidate read → lens doc
    assert P("how far is that fence")["intent"] == "depth"
    assert P("what star is that")["intent"] == "sky"
    assert P("which of these is healthier")["intent"] == "compare"
    assert P("what's the answer")["intent"] == "math"


def test_speech_that_names_nothing_is_never_turned_into_a_search():
    """"where is it" identifies no object — guessing a search would be inventing
    intent, so it falls through to the arbiter."""
    from dreamlayer.ai_brain.server.spoken_intent import parse_spoken_intent as P
    assert P("where is it") is None
    assert P("the weather is nice today") is None
    assert P("") is None and P(None) is None
    assert P("hm") is None


def test_spoken_intent_is_capped_and_never_raises():
    from dreamlayer.ai_brain.server.spoken_intent import parse_spoken_intent as P, MAX_TEXT
    r = P("find my " + "x" * 5000)
    assert r is None or len(r["said"]) <= MAX_TEXT
    for junk in (12345, 3.14, ["a"], {"b": 1}, True):
        P(junk)


def test_a_spoken_intent_expires_and_is_veil_gated():
    import tempfile
    from dreamlayer.ai_brain.server.server import Brain
    b = Brain(tempfile.mkdtemp())
    assert b.note_spoken_intent("where are my keys")["intent"] == "find"
    assert b.pending_intent()["terms"] == ["keys"]
    b.clear_intent()
    assert b.pending_intent() is None
    # one utterance steers ONE look, then it's gone
    b.note_spoken_intent("find my wallet")
    b.INTENT_TTL_S = -1.0                              # force expiry
    assert b.pending_intent() is None
    # under the shield nothing is remembered, not even briefly
    b.INTENT_TTL_S = 20.0
    b.config.network_mode = "lan_only"
    assert b.note_spoken_intent("where are my keys")["ok"] is False
    assert b.pending_intent() is None


# Tier 4 — it learns you, and stops asking

def test_a_learned_habit_makes_a_close_call_fire_instead_of_asking():
    from dreamlayer.orchestrator.glance import GlancePriors, GlanceArbiter, \
        GlanceReading, GlanceContext, LensBid, LensCandidate

    class A(LensCandidate):
        lens, label = "a", "A"
        def bid(self, reading, ctx):
            return LensBid("a", "A", 0.60, "a")

    class B(LensCandidate):
        lens, label = "b", "B"
        def bid(self, reading, ctx):
            return LensBid("b", "B", 0.55, "b")      # within the 0.2 gap → offer

    reading = GlanceReading("text", 0.9, {})
    naive = GlanceArbiter(candidates=[A(), B()], priors=GlancePriors())
    assert naive.arbitrate(reading, GlanceContext()).kind == "offer"

    priors = GlancePriors()
    for _ in range(5):                                # you always pick A here
        priors.reinforce_at("text", "a", "morning")
    taught = GlanceArbiter(candidates=[A(), B()], priors=priors)
    d = taught.arbitrate(reading, GlanceContext(hour=8))
    assert d.kind == "fire" and d.winner.lens == "a"


def test_priors_are_learned_per_time_of_day_and_stay_bounded():
    from dreamlayer.orchestrator.glance import GlancePriors, SCENES, DAYPARTS
    p = GlancePriors()
    p.reinforce_at("text", "read", "morning")
    assert p.boost_at("text", "read", "morning") > 0
    assert p.boost_at("text", "read", "night") > 0     # the general prior still counts
    # a crafted scene or daypart can never grow the file
    p.reinforce_at("../../etc/passwd", "read", "morning")
    p.reinforce_at("text", "read", "not-a-daypart")
    for key in p._c:
        base = key.split("@")[0]
        assert base in SCENES
        if "@" in key:
            assert key.split("@")[1] in DAYPARTS
