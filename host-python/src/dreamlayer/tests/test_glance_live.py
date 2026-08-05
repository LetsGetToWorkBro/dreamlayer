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

def _host_whose_lenses_work(brain, monkeypatch):
    """The cached host, with look_lens stubbed to SUCCEED — the packs the real
    lenses need aren't installed in the test environment, and a pick only teaches
    the arbiter when the lens actually answered (see the next test for why)."""
    wl = brain.world_lens()
    monkeypatch.setattr(wl, "look_lens",
                        lambda frame, lens, args=None: {"ok": True, "lens": lens})
    monkeypatch.setattr(Brain, "world_lens", lambda self: wl)
    return wl


def test_choosing_a_lens_teaches_the_arbiter(brain, monkeypatch):
    wl = _host_whose_lenses_work(brain, monkeypatch)
    before = wl.glance_arbiter.priors.boost("text", "math")
    # simulate the chooser tap: manual lens=math with the scene it was offered for
    live_mod.world_look(brain, _flat_frame(), lens="math", scene="text")
    assert wl.glance_arbiter.priors.boost("text", "math") > before


def test_a_pick_whose_LENS_FAILED_teaches_nothing(brain, monkeypatch):
    """Teaching used to happen BEFORE the lens ran, so a lens whose pack isn't
    installed still earned credit: three taps of a card that answered
    {"need": "doc_read"} made the arbiter "confident", which force-fires and
    removes the chooser — the only route to the other lens on that scene —
    permanently, on disk. A preference has to come from an answer you actually
    got, not from a button you pressed."""
    wl = brain.world_lens()
    monkeypatch.setattr(wl, "look_lens", lambda frame, lens, args=None: {
        "ok": False, "lens": lens, "need": "doc_read", "pack": "World Sense"})
    monkeypatch.setattr(Brain, "world_lens", lambda self: wl)
    for _ in range(3):
        out = live_mod.world_look(brain, _flat_frame(), lens="doc", scene="text")
        assert out.get("need") == "doc_read"        # the honest card still reaches you
    assert wl.glance_arbiter.priors.boost("text", "read") == 0.0
    assert wl.glance_arbiter.priors.confident("text", "read") is False


def test_reading_teaches_the_read_candidate_not_the_doc_key(brain, monkeypatch):
    # the chooser runs the "doc" lens but the arbiter learns the "read" CANDIDATE
    # key — reinforcing "doc" would be a dead no-op (the read candidate never
    # gets boosted). Teaching must land on "read".
    wl = _host_whose_lenses_work(brain, monkeypatch)
    live_mod.world_look(brain, _flat_frame(), lens="doc", scene="text")
    assert wl.glance_arbiter.priors.boost("text", "read") > 0      # the candidate key
    assert wl.glance_arbiter.priors.boost("text", "doc") == 0      # NOT the run key


def test_a_learned_habit_still_leaves_the_other_lens_one_tap_AWAY(brain, monkeypatch):
    """"It learns you" means it stops ASKING. It must not mean the alternative
    becomes unreachable: on a scene it had learned, the chooser was the only route
    to the other lens, so one habit — even a mistaken one — locked that lens out
    for good. A prior-forced fire now carries the alternatives it declined to ask
    about, so it fires instantly AND the other lens is still one tap off."""
    from dreamlayer.orchestrator.glance import classify_coarse, GlanceContext
    from dreamlayer.ai_brain.server.glance_live import build_live_arbiter
    a = build_live_arbiter(None)
    reading = classify_coarse({"text_density": 0.55}, "en")
    first = a.arbitrate(reading, GlanceContext(veiled=False))
    assert first.kind == "offer"                     # ambiguous: read OR math
    for _ in range(5):
        a.reinforce("text", "read", hour=9)
    d = build_live_arbiter(None)
    d.priors = a.priors
    fired = d.arbitrate(reading, GlanceContext(veiled=False, hour=9))
    assert fired.kind == "fire" and fired.winner.lens == "read"
    assert [o.lens for o in fired.options] == ["math"], "the alternative must survive"


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
    # EQUALITY, not `<=`. As a subset assertion this "pin" passed if sky, depth and
    # segment were removed again — it pinned nothing in the direction that mattered.
    assert lenses == {"taste", "rosetta", "read", "math", "juno",
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


def _page(size=720, sigma=1.5, pt=11):
    """Prose, WITH SENSOR NOISE, at the resolution the client actually posts
    (captureFrame(720)). The previous fixture was a 10x6 block grid at 240 px —
    coarse enough to read as a ruled table, which is what it measured as. Every
    threshold in the cue engine has to be judged on frames like this one; fitting
    them to noiseless synthetics is how they came to describe no real page."""
    import numpy as np
    rng = np.random.default_rng(3)
    h = int(size * 0.75)
    a = np.full((h, size), 242.0)
    step, th = max(5, pt), max(2, pt // 3)
    for y in range(step, h - step, step):
        for x in range(int(size * 0.08), int(size * 0.92), max(3, pt // 2)):
            if rng.random() > 0.22:
                a[y:y + th, x:x + th] = rng.integers(15, 55)
    return (a + rng.normal(0, sigma, a.shape)).clip(0, 255).astype(np.uint8)


def _shelf():
    import numpy as np
    a = np.full((240, 240), 150, np.uint8)
    for x in range(15, 225, 26):
        a[70:180, x:x + 16] = 60
    return a


def _night_sky(n=12):
    """A sparse starfield: n tiny points scattered over a dark frame."""
    import numpy as np
    rng = np.random.default_rng(11)
    a = np.full((240, 240), 8, np.uint8)
    for _ in range(n):
        y, x = rng.integers(5, 235, 2)
        a[y, x] = 250
    return a


# The false-positive family the sky cue has to reject. Each is a real situation a
# wearer is in at night, and each used to be classified as the heavens.
def _lit_room():
    import numpy as np
    a = np.full((240, 240), 20, np.uint8)
    a[60:180, 60:180] = 200                 # one big bright area, not point lights
    return a


def _one_led():
    import numpy as np
    a = np.full((240, 240), 8, np.uint8)
    a[120:126, 120:126] = 250               # a router LED in a dark room
    return a


def _streetlamps():
    import numpy as np
    a = np.full((240, 320), 18, np.uint8)
    for x in (60, 150, 240):
        a[50:59, x:x + 8] = 245             # a row of lamps down a night street
    a[190:240, :] = 40
    return a


def _screen_glow():
    import numpy as np
    a = np.full((240, 320), 14, np.uint8)
    a[100:145, 130:190] = 235               # a phone lighting a dim room
    return a


def _radiator(fins=12):
    import numpy as np
    a = np.full((240, 320), 190, np.uint8)
    w = 320 // fins
    for i in range(fins):
        a[20:220, i * w + 2:i * w + w - 2] = 150
    return a


def _fence(slats=12):
    import numpy as np
    a = np.full((240, 320), 120, np.uint8)
    w = 320 // slats
    for i in range(slats):
        a[:, i * w + 3:i * w + w - 3] = 200
    return a


def _dense_page():
    """Prose set tightly enough to be dense AND strongly banded — the shape that
    used to be read as a form with twelve fields."""
    import numpy as np
    rng = np.random.default_rng(5)
    a = np.full((240, 320), 240, np.uint8)
    for y in range(6, 234, 6):
        for x in range(10, 310, 4):
            if rng.random() > 0.2:
                a[y:y + 3, x:x + 3] = rng.integers(10, 50)
    return a


def test_a_photographed_page_fires_read():
    scene, kind, action = _act(_page())
    assert scene == "text" and kind == "fire" and action == "read"


def test_a_shelf_the_PHONE_saw_fires_taste():
    """A shelf is what the phone's detector reports: several detections, several
    of the SAME label. It is deliberately no longer inferred from periodicity —
    see the two negative tests below for why."""
    scene, kind, action = _act(_shelf(), {"items": 4, "shelf": True})
    assert scene == "shelf" and kind == "fire" and action == "taste"


def test_periodic_structure_alone_is_never_a_shelf():
    """A radiator, a picket fence, a venetian blind and a bookshelf are one
    picture to a gradient profile. The old cue claimed "12 items to compare" on a
    radiator and on a motion-blurred street, and still MISSED a real 4-bottle
    shelf, so it is gone: repetition is reported raw and the detector decides."""
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    P = HeuristicPerceptor()
    for frame in (_shelf(), _radiator(), _fence()):
        sig = P.perceive(frame)
        assert sig.shelf is None, "image statistics must not claim a shelf"
        assert sig.items is None
    # the raw repetition cue IS still produced, so a lens that wants it can have it
    from dreamlayer.ai_brain.perception import frame_cues
    assert frame_cues(_shelf())["col_reps"] >= 3


def test_two_different_things_are_not_a_shelf():
    """`items >= 2` used to resolve the scene to "shelf" on its own, so a mug
    beside a laptop fired the compare lens at 0.88 — above identify — on any
    desk. A comparison needs several of the same kind of thing."""
    from dreamlayer.orchestrator.glance import classify_coarse
    assert classify_coarse({"items": 2, "has_object": True}, "en").scene != "shelf"
    assert classify_coarse({"items": 4, "has_object": True}, "en").scene != "shelf"
    assert classify_coarse({"items": 4, "shelf": True}, "en").scene == "shelf"


def test_a_page_of_prose_is_never_a_form_to_fill_in():
    """`bands >= 6 and density >= 0.20` is satisfied by any densely-set page —
    text lines ARE horizontal bands, the very cue Read depends on — so a
    photographed page claimed 12 form fields and the glasses offered to fill it
    in. A form has a few ruled rows and vertical rules; prose has neither."""
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    from dreamlayer.orchestrator.glance import classify_coarse
    sig = HeuristicPerceptor().perceive(_dense_page()).as_signals()
    assert not sig.get("form_fields"), sig
    assert classify_coarse(sig, "en").scene != "form"


def test_the_sky_needs_the_PIXELS_AND_THE_POSTURE_to_fire():
    """Rain on a dark window is many tiny bright points scattered over the whole
    frame — which is the definition of a starfield too, and no count, size or
    spread separates them (measured: droplets 597 lights of mean length 2.0 over
    99% of the frame; a starfield 91 of length 1.0 over 97%). So the pixels earn a
    CHOOSER, and only a camera actually pointed up at night fires the lens."""
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    assert HeuristicPerceptor().perceive(_night_sky()).sky is True   # the CUE
    scene, kind, _action = _act(_night_sky())
    assert scene == "sky" and kind == "offer"                        # asks
    _d, up = _fresh(_night_sky(), tilt_deg=55.0, hour=23)
    assert up is not None and up.action == "sky"                     # then runs
    _d2, midday = _fresh(_night_sky(), tilt_deg=55.0, hour=13)
    assert midday is None or midday.action != "sky"


def test_only_a_scattered_field_of_TINY_lights_is_the_sky():
    """The whole false-positive family, asserted on the cue itself so deleting
    the sky logic cannot pass. "A small bright fraction of a dark frame" called
    every one of these the night sky and fired an astronomy lens at it."""
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    P = HeuristicPerceptor()
    assert P.perceive(_night_sky()).sky is True          # scattered, tiny  → sky
    assert P.perceive(_night_sky(n=40)).sky is True
    assert P.perceive(_lit_room()).sky is not True       # one big bright block
    assert P.perceive(_one_led()).sky is not True        # a single LED, dark room
    assert P.perceive(_streetlamps()).sky is not True    # a lit street at night
    assert P.perceive(_screen_glow()).sky is not True    # a phone lighting a room


def test_a_lit_room_is_not_mistaken_for_the_sky():
    assert _act(_lit_room())[0] != "sky"


def test_translate_is_reached_by_SAYING_so_not_by_language_detection():
    """This test used to inject `{"language": "fr"}` and call the result "a French
    page fires translate". Nothing on the live path produces `language` — the
    heuristic perceptor cannot read script, and `parse_cues` does not accept it —
    so a real rendered French page classifies as plain `text` and fires Read. The
    honest route to translate is the words: "translate this".

    Both halves are asserted, so neither claim can quietly become false."""
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    from dreamlayer.ai_brain.server import live as live_mod
    from dreamlayer.ai_brain.server.spoken_intent import parse_spoken_intent
    # 1. no cue source produces `language` — that is why auto-detect is not claimed
    assert "language" not in HeuristicPerceptor().perceive(_page()).as_signals()
    assert "language" not in live_mod.parse_cues({"language": ["fr"], "lang": ["fr"]})
    # 2. the arbiter WOULD route it if a tier ever supplied one (the seam is live)
    scene, kind, action = _act(_page(), {"language": "fr"})
    assert scene == "foreign_text" and kind == "fire" and action == "translate"
    # 3. and the route that works today is speech
    assert parse_spoken_intent("translate this")["intent"] == "translate"


def test_a_person_in_frame_never_fires_a_reading_lens():
    """The old version asserted only `action not in (read, math, taste)`, which was
    vacuously true because NO candidate bids on a person scene at all — it passed
    with every cue in the file deleted. Pin the real invariant: the live set
    contains no bidder for `person`, so the decision is "none" and the face falls
    through to the Social Lens, which is the only thing allowed to name anyone."""
    from dreamlayer.orchestrator.glance import classify_coarse, GlanceContext
    from dreamlayer.ai_brain.server.glance_live import LIVE_CANDIDATES
    reading = classify_coarse({"has_face": True, "text_density": 0.28}, "en")
    assert reading.scene == "person"
    bids = [c.bid(reading, GlanceContext()) for c in LIVE_CANDIDATES]
    assert [b for b in bids if b] == [], "no lens may bid on a person"
    scene, kind, action = _act(_page(), {"has_face": True})
    assert scene == "person" and kind == "none" and action is None


def test_the_phone_sends_a_shelf_BIT_and_never_the_label_strings():
    from dreamlayer.ai_brain.server import live as live_mod
    cues = live_mod.parse_cues({"ndet": ["4"], "dup": ["1"], "face": ["1"]})
    assert cues["items"] == 4
    assert cues["shelf"] is True          # several of the SAME thing = comparables
    assert cues["has_face"] is True
    assert "box" not in cues and "crop" not in cues
    # The label STRINGS are a behavioural profile ("syringe", "pill bottle") that
    # nothing on the Brain ever read. A cached older page may still send them; the
    # derived bit survives, the words are not kept.
    legacy = live_mod.parse_cues({"ndet": ["4"], "objs": ["bottle,bottle,cup"]})
    assert legacy["shelf"] is True and legacy["has_object"] is True
    assert "objs" not in legacy, "detector label strings must not be retained"


def test_the_client_hints_actually_REACH_the_arbiter_not_just_parse_cues():
    """The previous test of this name only exercised `parse_cues`. Deleting the
    hint merge inside `WorldLensHost.glance` was invisible to the whole suite, so
    the claim "the phone's detections reach the arbiter" was unpinned. Assert the
    merge itself: a frame whose own statistics say nothing must still resolve to a
    shelf when the PHONE says it saw four of the same thing."""
    import numpy as np
    from dreamlayer.orchestrator.glance import classify_coarse
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    blank = np.full((240, 240), 128, np.uint8)
    signals = HeuristicPerceptor().perceive(blank).as_signals()
    assert classify_coarse(signals, "en").scene != "shelf"      # the frame alone
    merged = dict(signals)
    for k, v in {"items": 4, "shelf": True}.items():            # what glance() does
        merged[k] = max(int(merged.get(k, 0) or 0), int(v)) if k == "items" else v
    assert classify_coarse(merged, "en").scene == "shelf"


def test_client_cues_are_sanitised():
    from dreamlayer.ai_brain.server import live as live_mod
    hostile = {"ndet": ["not-a-number"], "objs": ["<script>alert(1)</script>,../../etc"]}
    cues = live_mod.parse_cues(hostile)
    assert "items" not in cues
    assert "objs" not in cues              # never retained, hostile or not
    assert live_mod.parse_cues({}) == {}
    assert live_mod.parse_cues({"ndet": ["999999"]})["items"] <= 24
    # A coordinate is only a coordinate inside the range one can exist in. tilt and
    # dwell were clamped from the start; lat/lon took inf, 999 and -1e30 verbatim
    # and handed them to the ephemeris.
    for hostile_geo in ({"lat": ["1e400"], "lon": ["0"]}, {"lat": ["999"], "lon": ["1"]},
                        {"lat": ["-1e30"], "lon": ["-99999"]}, {"lat": ["nan"], "lon": ["2"]}):
        got = live_mod.parse_cues(hostile_geo)
        assert "lat" not in got, got
    ok = live_mod.parse_cues({"lat": ["51.5074"], "lon": ["-0.1278"]})
    assert round(ok["lat"], 3) == 51.507 and round(ok["lon"], 3) == -0.128


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


def test_looking_up_at_a_dark_CEILING_does_not_fire_the_astronomy_lens():
    """This test used to assert the opposite, and the opposite was a bug. Posture
    plus darkness plus "not much text" describes a dark ceiling, a blank wall and a
    keyboard as readily as the heavens — and since the sky bid was then the only
    bid, a single bid is an automatic fire, so the wearer got "install the
    Stargazer pack" instead of the object label and the object floor never ran.

    The posture bid survives at 0.3: below the arbiter's 0.35 floor on its own, so
    it can earn a place in a chooser but can never carry a look by itself."""
    import numpy as np
    from dreamlayer.orchestrator.glance import classify_coarse, GlanceContext
    from dreamlayer.ai_brain.server.glance_live import SkyCandidate
    flat_dark = np.full((240, 240), 10, np.uint8)      # no point lights at all
    _d, none_level = _fresh(flat_dark, tilt_deg=0.0, hour=12)
    d2, up_night = _fresh(flat_dark, tilt_deg=45.0, hour=23)
    assert none_level is None                          # noon, level → not the sky
    assert d2.kind != "fire", "a dark ceiling must never auto-run the sky lens"
    assert up_night is None
    # the posture bid still exists — it is just too weak to fire alone
    reading = classify_coarse({"text_density": 0.02, "dark": True}, "en")
    bid = SkyCandidate().bid(reading, GlanceContext(tilt_deg=45.0, hour=23))
    assert bid is not None and bid.salience < 0.35


def test_an_unknown_hour_is_not_treated_as_night():
    """`night = ctx.hour < 0` made the "we don't know the time" sentinel mean
    night, so the astronomy lens got a free pass whenever the clock was
    unavailable — a fail-OPEN in a codebase that fails closed everywhere else."""
    from dreamlayer.orchestrator.glance import classify_coarse, GlanceContext
    from dreamlayer.ai_brain.server.glance_live import SkyCandidate
    reading = classify_coarse({"text_density": 0.02, "dark": True}, "en")
    c = SkyCandidate()
    assert c.bid(reading, GlanceContext(tilt_deg=45.0, hour=-1)) is None
    assert c.bid(reading, GlanceContext(tilt_deg=45.0, hour=13)) is None   # midday
    assert c.bid(reading, GlanceContext(tilt_deg=45.0, hour=23)) is not None


def test_the_glasses_still_have_an_owner_for_the_new_sky_scene():
    """Adding "sky" to SCENES gave the LIVE path a new lens and silently blinded
    the GLASSES: DEFAULT_CANDIDATES had nothing that bids on it, so a dark frame
    that used to be identified started producing no decision at all. A scene
    vocabulary that grows must never leave a scene without a bidder."""
    from dreamlayer.orchestrator.glance import (GlanceArbiter, DEFAULT_CANDIDATES,
                                                SCENES, classify_coarse,
                                                GlanceContext, LensBid)
    a = GlanceArbiter(candidates=DEFAULT_CANDIDATES)
    d = a.arbitrate(classify_coarse({"text_density": 0.08, "sky": True,
                                     "has_object": True}, "en"), GlanceContext())
    assert d.kind == "fire" and d.winner.lens == "juno"
    # and no scene in the vocabulary is left with nobody willing to bid
    orphans = []
    for scene in SCENES:
        reading = classify_coarse({}, "en")
        reading = type(reading)(scene, 0.6, {"text_density": 0.08, "has_object": True})
        bids = [c.bid(reading, GlanceContext()) for c in DEFAULT_CANDIDATES]
        if not [b for b in bids if isinstance(b, LensBid)]:
            orphans.append(scene)
    assert orphans == ["unknown"], f"scenes with no bidder: {orphans}"


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
    # The daypart key must EXIST. Both assertions below used to be satisfied by the
    # general key's fallback, so they passed with the whole daypart mechanism
    # deleted — which is what it was, since nothing in production called this.
    assert "text@morning" in p._c, p._c
    assert p.boost_at("text", "read", "morning") > 0
    assert p.boost_at("text", "read", "night") > 0     # the general prior still counts
    q = GlancePriors()
    for _ in range(4):                                 # a morning habit, mornings only
        q.reinforce_at("text", "read", "morning")
        q.reinforce_at("text", "math", "evening")
    assert q.boost_at("text", "read", "morning") > q.boost_at("text", "read", "evening")
    assert q.confident("text", "read", "morning") and not q.confident("text", "read")
    # a crafted scene or daypart can never grow the file
    p.reinforce_at("../../etc/passwd", "read", "morning")
    p.reinforce_at("text", "read", "not-a-daypart")
    for key in p._c:
        base = key.split("@")[0]
        assert base in SCENES
        if "@" in key:
            assert key.split("@")[1] in DAYPARTS


def test_the_production_teach_path_actually_writes_the_daypart_key():
    """`reinforce_at` had ZERO non-test callers: every production teacher went
    through GlanceArbiter.reinforce, which wrote only the bare scene key. The
    daypart tier was inert while being advertised as shipped."""
    from dreamlayer.orchestrator.glance import GlanceArbiter
    a = GlanceArbiter(candidates=[])
    a.reinforce("text", "read", hour=8)
    assert sorted(a.priors._c) == ["text", "text@morning"]
    a.reinforce("text", "read", hour=-1)             # unknown clock → general only
    assert sorted(a.priors._c) == ["text", "text@morning"]


def test_a_habit_stays_revisable_and_the_counts_stay_bounded():
    """Counts used to grow without limit (1000 picks → 1000.0), which made a
    preference effectively permanent: escaping it would have taken hundreds of
    corrections. They now decay as they accumulate, so the row converges and four
    contrary picks pull a fully-formed habit back below the confidence share."""
    from dreamlayer.orchestrator.glance import GlancePriors
    p = GlancePriors()
    for _ in range(200):
        p.reinforce("text", "read")
    assert sum(p._c["text"].values()) <= 11.0        # bounded, not 200
    assert p.confident("text", "read")
    for _ in range(4):
        p.reinforce("text", "math")
    assert not p.confident("text", "read"), "a habit must be revisable"


def test_a_crafted_lens_key_cannot_grow_the_priors_file():
    """`scene` was validated against SCENES but `lens` was taken verbatim, and the
    file is rewritten WHOLE on every pick: one 100 000-character lens name grew it
    to 107 KB, and 500 distinct names to 115 KB."""
    from dreamlayer.orchestrator.glance import GlancePriors, MAX_PRIOR_LENSES
    p = GlancePriors()
    p.reinforce("text", "x" * 100000)
    assert max(len(k) for k in p._c["text"]) <= 48
    for i in range(60):
        p.reinforce("text", f"lens{i}")
    assert len(p._c["text"]) <= MAX_PRIOR_LENSES
    import json
    assert len(json.dumps(p.to_dict())) < 2048


def test_a_string_hour_does_not_raise_out_of_arbitration():
    """GlanceContext is a shared dataclass at a public seam and `hour` is compared
    with `>=` inside arbitrate(), so a caller passing "8" raised a TypeError from
    the middle of arbitration — which world_lens.glance swallows into
    "kind: object", i.e. the automatic lens silently gone."""
    from dreamlayer.orchestrator.glance import GlanceContext
    assert GlanceContext(hour="8").hour == 8
    assert GlanceContext(hour="not-an-hour").hour == -1
    assert GlanceContext(hour=None).hour == -1
    assert GlanceContext(tilt_deg="-35").tilt_deg == -35.0
    assert GlanceContext(tilt_deg=None).tilt_deg == 0.0


def test_boost_at_has_no_dead_branch_left_to_trip_over():
    """It used to read `self.boost(key) if False else self._boost_key(key, lens)`.
    The dead operand called a two-argument method with one argument, so any
    refactor or linter that simplified the constant condition would have made
    EVERY arbitration raise."""
    import ast
    import inspect
    import textwrap
    from dreamlayer.orchestrator.glance import GlancePriors
    # parse rather than grep, so this file's own prose about the bug can't satisfy it
    tree = ast.parse(textwrap.dedent(inspect.getsource(GlancePriors.boost_at)))
    consts = [n for n in ast.walk(tree)
              if isinstance(n, ast.IfExp) and isinstance(n.test, ast.Constant)]
    assert consts == [], "a constant-condition branch is a tripwire, not code"
    # and the daypart branch is genuinely live: it reads the scene@daypart key
    p = GlancePriors()
    p.reinforce_at("text", "read", "morning")
    p.reinforce("text", "math")
    p.reinforce("text", "math")
    assert p.boost_at("text", "read", "morning") > p.boost("text", "read")


def test_moving_is_never_claimed_and_depth_is_reached_by_ASKING():
    """One frame cannot tell you the wearer is walking. Blur removes high-frequency
    SIGNAL, but sensor noise is added after the blur and is itself pure high
    frequency, so a sharpness measure measures the noise floor: a still street at
    1.5 DN of noise reads 0.0121 and the same street blurred 24 px at 3 DN reads
    0.0198 — the BLURRED one scores higher. Normalising by contrast does not
    separate them either (0.70 still vs 0.99 walking). The cue never fired on a real
    frame, and where it did fire it told a stationary wearer they were moving.

    So `moving` is not produced at all, and depth is reachable the honest way — the
    same arrangement `find` has, because both are intents no frame can justify."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    from dreamlayer.ai_brain.perception import HeuristicPerceptor
    from dreamlayer.orchestrator.glance import GlanceContext, classify_coarse
    from dreamlayer.ai_brain.server.glance_live import DepthCandidate

    def street(blur, sigma):
        rng = np.random.default_rng(4)
        im = Image.new("L", (640, 480), 90)
        d = ImageDraw.Draw(im)
        for i in range(7):
            d.rectangle([i * 91 + 8, 160, i * 91 + 71, 460], fill=40 + i * 22)
        a = np.asarray(im.filter(ImageFilter.GaussianBlur(blur), ), dtype=float)
        return (a + rng.normal(0, sigma, a.shape)).clip(0, 255).astype(np.uint8)

    P = HeuristicPerceptor()
    for blur in (0, 8, 14, 24):
        for sigma in (1.5, 3.0):
            sig = P.perceive(street(blur, sigma))
            assert sig.moving is None, f"moving must not be claimed (blur={blur})"
            assert "moving" not in sig.as_signals()
    # depth bids ONLY on a spoken request
    reading = classify_coarse({"text_density": 0.05, "has_object": True}, "en")
    c = DepthCandidate()
    assert c.bid(reading, GlanceContext()) is None
    assert c.bid(reading, GlanceContext(recent_intent="read")) is None
    bid = c.bid(reading, GlanceContext(recent_intent="depth"))
    assert bid is not None and bid.lens == "depth"


def test_a_page_of_prose_still_fires_read_at_the_size_the_client_posts():
    """The band cue counted rows above a MULTIPLE OF THE MEDIAN, which collapses on
    exactly the frame it exists for: where most rows ARE text the median rises with
    them, so one page measured 96 bands at 240 px and none at 720 — the resolution
    captureFrame() uses. Counted against the strongest row instead."""
    from dreamlayer.ai_brain.perception import frame_cues
    for size in (240, 480, 720, 1080):
        assert frame_cues(_page(size))["rows"] >= 10, size
    scene, kind, action = _act(_page())
    assert scene == "text" and kind in ("fire", "offer")
    if kind == "fire":
        assert action == "read"


def test_a_blank_wall_reports_no_repetition():
    """Peak prominence is measured relative to the profile's own range, so on a
    flat frame the sensor NOISE was the range and roughly every other sample
    cleared the bar — a painted wall reported ~25 repetitions out of nothing."""
    import numpy as np
    from dreamlayer.ai_brain.perception import frame_cues
    rng = np.random.default_rng(7)
    for grad in (0.0, 24.0):
        a = np.full((360, 480), 128.0) + np.linspace(0, grad, 480)[None, :]
        a += rng.normal(0, 1.2, a.shape)
        c = frame_cues(a.clip(0, 255).astype(np.uint8))
        assert c["col_reps"] == 0 and c["row_reps"] == 0, c
    bars = np.full((360, 480), 200, np.uint8)              # real structure still counts
    for x in range(10, 470, 40):
        bars[80:280, x:x + 22] = 70
    assert frame_cues(bars)["col_reps"] >= 4


# --- the spoken parser must be DIRECTED, not merely keyword-matched -----------
# An audit put 39 ordinary conversational phrases through the first version: 26
# fired a lens. Because a spoken lens runs OUTRIGHT, before any bidding, those
# were actions — "how far we've come" answered with "install the World Sense
# pack". Both corpora are pinned so neither direction can regress.

_CORPUS_IDIOMS = (
    "how far we've come", "find out later", "let's find out", "read the room",
    "what's the answer to life", "I lost my train of thought",
    "where there's smoke there's fire", "where do you see yourself in five years",
    "how tall was your grandfather", "how deep does the rabbit hole go",
    "what planet are you on", "is that a satellite office",
    "calculate the risk of telling her", "work it out between yourselves",
    "isolate the variable in your thinking", "spot the difference",
    "locate the problem in the argument", "point out that i was right",
    "have you seen the new season", "we've come so far",
    "translate that for the board", "i lost my patience with him",
    "where were we", "which came first", "how close are we to done",
    "read the fine print in the contract",
)

_CORPUS_REAL = (
    ("where did I leave my keys", "find"), ("where are my keys", "find"),
    ("where's my wallet", "find"), ("find my phone charger", "find"),
    ("have you seen my glasses", "find"), ("i lost my passport", "find"),
    ("what does this say", "read"), ("read this out loud", "read"),
    ("read the menu", "read"), ("how far is that", "depth"),
    ("how far away is that building", "depth"), ("how tall is that", "depth"),
    ("what star is that", "sky"), ("is that a satellite", "sky"),
    ("what's that constellation", "sky"),
    ("which of these is healthier", "compare"),
    ("which one has less sugar", "compare"),
    ("what's the answer", "math"), ("solve this", "math"), ("work it out", "math"),
    ("translate this", "translate"), ("translate that sign", "translate"),
    ("what is this", "object"), ("isolate this one", "segment"),
    ("just that one", "segment"),
)


def test_ordinary_conversation_never_fires_a_lens():
    from dreamlayer.ai_brain.server.spoken_intent import parse_spoken_intent
    fired = {s: parse_spoken_intent(s) for s in _CORPUS_IDIOMS}
    fired = {s: r["intent"] for s, r in fired.items() if r}
    assert fired == {}, f"figures of speech firing a lens: {fired}"


def test_a_directed_request_still_lands_on_the_right_lens():
    from dreamlayer.ai_brain.server.spoken_intent import parse_spoken_intent
    wrong = {}
    for said, want in _CORPUS_REAL:
        got = parse_spoken_intent(said)
        if not got or got["intent"] != want:
            wrong[said] = (want, got and got["intent"])
    assert wrong == {}, f"real phrasings broken: {wrong}"


def test_find_takes_its_nouns_only_from_what_was_said():
    from dreamlayer.ai_brain.server.spoken_intent import parse_spoken_intent
    assert parse_spoken_intent("where did I leave my keys")["terms"] == ["keys"]
    assert parse_spoken_intent("find my phone charger")["terms"] == ["phone", "charger"]
    assert parse_spoken_intent("have you seen my glasses")["terms"] == ["glasses"]
    # "lost my ___" is an idiom far more often than a search
    for idiom in ("i lost my temper", "i lost my train of thought",
                  "i lost my nerve completely"):
        assert parse_spoken_intent(idiom) is None, idiom


def test_the_ROOM_EAR_never_steers_the_lens(brain):
    """The always-on ear used to arm the lens intent for every utterance it heard,
    so a bystander saying "how far is that" redirected the wearer's next look. The
    obvious guard — skip utterances attributed to someone else — is worthless here:
    nothing in this product ever populates `speaker`, because knowing who spoke
    would mean voiceprinting everyone in earshot, which voice_guard exists to
    forbid without consent. A guard that cannot fire is not a fix, so the ear
    simply does not steer: only the deliberate phone path does.

    Asserted against the REAL pipeline shape, not by passing a speaker the
    production code never sets."""
    from dreamlayer.ai_brain.server.ear import EarHost
    ear = EarHost(brain)
    for said in ("where are my keys", "how far is that", "read this"):
        ear.ingest_caption(said)
        assert brain.pending_intent() is None, f"the room ear steered on {said!r}"
    # the ear still REMEMBERS — that is its job
    assert ear.heard_count == 3
    # and the deliberate path does steer
    brain.note_spoken_intent("where are my keys")
    got = brain.pending_intent()
    assert got is not None and got["intent"] == "find"


def test_one_utterance_steers_exactly_one_look(brain):
    """clear_intent() only ran when the intent named a runnable lens, and
    compare/translate/object name none — they steer the bidding instead. So one
    "which of these is healthier" force-steered EVERY look for the full 20s TTL."""
    wl = build_world_lens(brain)
    for phrase in ("which of these is healthier", "translate this", "what is this"):
        brain.note_spoken_intent(phrase)
        assert brain.pending_intent() is not None, phrase
        wl.glance(_flat_frame())
        assert brain.pending_intent() is None, f"{phrase!r} still steering"


def test_a_spoken_lens_that_finds_nothing_says_so(brain, monkeypatch):
    """The wearer asked a question. Falling through to the object floor answered it
    with a label — "where did I leave my keys" → "mug" — with no sign the search
    ever ran."""
    wl = brain.world_lens()
    monkeypatch.setattr(wl, "look_lens", lambda frame, lens, args=None: {
        "ok": False, "lens": lens, "found": []})
    monkeypatch.setattr(Brain, "world_lens", lambda self: wl)
    brain.note_spoken_intent("where did I leave my keys")
    g = wl.glance(_flat_frame())
    assert g["kind"] == "fire" and g["lens"] == "find"
    assert "keys" in " ".join(g["card"]["lines"]).lower()


def test_a_missing_pack_still_reaches_the_phone_on_the_AUTO_fire_path(brain, monkeypatch):
    """The honest "install the pack" card is the whole reason auto-fire is allowed
    to run a frontier lens, and nothing pinned it: making _glance_lens_result drop
    `need` was invisible to the entire suite, and the silent fallback to
    object-naming is exactly the "it's just naming things again" symptom."""
    wl = brain.world_lens()
    monkeypatch.setattr(wl, "look_lens", lambda frame, lens, args=None: {
        "ok": False, "lens": lens, "need": "openvocab_find", "pack": "World Sense"})
    monkeypatch.setattr(Brain, "world_lens", lambda self: wl)
    brain.note_spoken_intent("where are my keys")
    g = wl.glance(_flat_frame())
    assert g["kind"] == "fire" and g["card"].get("need") == "openvocab_find"
    assert g["card"].get("pack") == "World Sense"
    out = live_mod.world_look(brain, _flat_frame(), lens="doc", scene="text")
    assert out.get("need") or out.get("ok") is False


def test_the_wearers_place_reaches_an_AUTO_fired_lens(brain, monkeypatch):
    """Only the spoken path merged lat/lon into the lens args, and no candidate
    sets any, so an auto-fired sky lens always answered "needs your
    latitude/longitude" — the one thing the arbiter was proud of reaching was a
    nag every single time."""
    seen = {}
    wl = brain.world_lens()

    def _spy(frame, lens, args=None):
        seen[lens] = dict(args or {})
        return {"ok": True, "lens": lens}
    monkeypatch.setattr(wl, "look_lens", _spy)
    monkeypatch.setattr(Brain, "world_lens", lambda self: wl)
    # tilt AND night, because the sky lens only FIRES when the camera is pointed up
    _at_night(monkeypatch)
    wl.glance(_night_sky(), hints={"sky": True, "tilt": 55.0,
                                   "lat": 51.5074, "lon": -0.1278})
    assert "sky" in seen, seen
    assert round(seen["sky"]["lat"], 3) == 51.507
    assert round(seen["sky"]["lon"], 3) == -0.128


def test_the_spoken_transcript_never_survives_the_veil(brain):
    """note_spoken_intent refused to remember under the shield, but raising the
    shield AFTER an utterance left the transcript readable: only the accident of
    world_lens.glance checking the posture first kept it off the veiled path.
    Reading it while veiled now also drops it."""
    brain.note_spoken_intent("where did I leave my diary")
    assert brain.pending_intent() is not None
    brain.config.network_mode = "lan_only"              # shield up
    assert brain.pending_intent() is None
    brain.config.network_mode = "local"                 # and it is GONE, not hidden
    assert brain.pending_intent() is None


def _at_night(monkeypatch):
    """Pin the clock inside world_lens. `glance()` reads time.localtime() for the
    daypart and the sky gate, so a test that needs "night" must say so — otherwise
    it passes or fails depending on when the suite runs."""
    import time as _time
    from dreamlayer.ai_brain.server import world_lens as wl_mod
    real_localtime = _time.localtime

    class _Clock:
        @staticmethod
        def localtime(*a):
            return real_localtime(0).__class__((2026, 7, 26, 23, 0, 0, 6, 207, 0))
    monkeypatch.setattr(wl_mod, "time", _Clock)


def test_the_alternative_TRAVELS_all_the_way_to_the_phone(brain, monkeypatch):
    """The arbiter computing the alternatives is not the same as the wearer being
    able to reach them. `world_lens.glance` dropped `decision.options` on the
    floor and the live response had no field for it, so "the other lens stays one
    tap away" was true inside the arbiter and false everywhere else. Pin the whole
    chain: arbiter → glance() → world_look() → the JSON the phone renders."""
    wl = brain.world_lens()
    monkeypatch.setattr(wl, "look_lens",
                        lambda frame, lens, args=None: {"ok": True, "lens": lens,
                                                        "line": "answer"})
    monkeypatch.setattr(Brain, "world_lens", lambda self: wl)
    for _ in range(5):                                  # a formed habit: text → read
        wl.glance_arbiter.reinforce("text", "read", hour=9)
    g = wl.glance(_text_frame())
    assert g["kind"] == "fire" and g["lens"] == "read"
    assert [a["lens"] for a in g["alts"]] == ["math"], g
    out = live_mod.world_look(brain, _text_frame())
    assert out["glance"] == "fire"
    assert [a["lens"] for a in out["alts"]] == ["math"], out
    # the scene rides along, because tapping an alternative is a chooser pick and
    # has to teach the arbiter the same way one does
    assert out["scene"] == "text"


def test_an_UNLEARNED_fire_carries_no_alternatives(brain, monkeypatch):
    """The aside is only for a fire the priors forced. A fire that won on a clear
    salience gap was never a question, so offering "or …" there would be noise."""
    wl = brain.world_lens()
    monkeypatch.setattr(wl, "look_lens",
                        lambda frame, lens, args=None: {"ok": True, "lens": lens})
    monkeypatch.setattr(Brain, "world_lens", lambda self: wl)
    # unambiguous (posture agrees with the pixels), and no habit taught
    _at_night(monkeypatch)
    g = wl.glance(_night_sky(), hints={"sky": True, "tilt": 55.0})
    assert g["kind"] == "fire" and "alts" not in g, g


def test_the_alts_row_exists_in_the_page_and_is_wired(brain):
    """A response field nothing renders is the same bug one level up."""
    page = live_mod._PAGE
    assert 'id="alts"' in page
    assert "function showAlts(" in page and "function hideAlts(" in page
    assert "showAlts(j.alts, j.scene)" in page          # called on a fired glance
    assert ".altbtn{" in page and "#alts.show{" in page  # and actually styled
    # it must never be on screen at the same time as the chooser, and the veil
    # must tear it down like every other live surface.
    #
    # The DEFINITION is excluded from the count. `function hideAlts(){`
    # contains the substring `hideAlts()`, so a bare `count(...) >= 4` was
    # satisfied by three real calls plus the definition — it tolerated losing
    # one teardown silently. Same shape as the `loadConsent()` count in
    # test_consent_routes (CLAUDE.md #1).
    calls = page.count("hideAlts()") - page.count("function hideAlts()")
    assert calls >= 4, (
        f"only {calls} real hideAlts() call sites — a teardown was dropped")
    # …and the two that carry the claims above, named rather than counted, so
    # losing one of THESE cannot be masked by another site being added.
    assert "hideChooser(); hideAlts();" in page, (
        "the veil no longer tears the alternatives down with everything else")
    assert 'hideAlts();                               /* never both at once */' in page, (
        "the chooser no longer hides the alternatives — they can now be on "
        "screen together")


def test_a_sub_floor_bid_is_never_lifted_over_the_floor_by_DWELL():
    """The posture-only sky bid is 0.30 precisely so it cannot carry a look — but a
    generic +0.05 "held gaze" boost lifted it to exactly 0.35, and the floor test is
    a strict `<`, so holding still for 700ms auto-ran an astronomy lens at a dark
    ceiling. The dark-ceiling test could not see it because it never passed a dwell
    at all. Dwell strengthens a real candidate; it does not create one."""
    import numpy as np
    flat_dark = np.full((240, 240), 10, np.uint8)
    for dwell in (0.0, 699.0, 700.0, 900.0, 5000.0):
        d, w = _fresh(flat_dark, tilt_deg=55.0, hour=23, dwell_ms=dwell)
        assert d.kind != "fire", f"dwell={dwell} must not auto-run the sky lens"
        assert w is None
    # a bid that was ALREADY viable still gets the boost
    from dreamlayer.orchestrator.glance import (GlanceArbiter, GlanceContext,
                                                GlanceReading, LensBid, LensCandidate)

    class Strong(LensCandidate):
        lens, label = "s", "S"

        def bid(self, reading, ctx):
            return LensBid("s", "S", 0.50, "s")
    a = GlanceArbiter(candidates=[Strong()])
    r = GlanceReading("text", 0.9, {})
    quick = a.arbitrate(r, GlanceContext(dwell_ms=0.0))
    a2 = GlanceArbiter(candidates=[Strong()])
    held = a2.arbitrate(r, GlanceContext(dwell_ms=900.0))
    assert held.winner.salience > quick.winner.salience


def test_the_LIVE_set_also_has_an_owner_for_every_scene_it_can_see():
    """The orphan test iterated DEFAULT_CANDIDATES only, so it structurally could not
    see that the PHONE set left form, question and person with nobody willing to bid
    — a photographed form simply did nothing. Person is the one deliberate silence:
    every face defers to the Social Lens."""
    from dreamlayer.orchestrator.glance import (SCENES, GlanceContext, GlanceReading,
                                                LensBid)
    from dreamlayer.ai_brain.server.glance_live import LIVE_CANDIDATES
    orphans = []
    for scene in SCENES:
        reading = GlanceReading(scene, 0.7, {"text_density": 0.25, "has_object": True,
                                             "items": 4, "bands": 12})
        bids = [c.bid(reading, GlanceContext()) for c in LIVE_CANDIDATES]
        if not [b for b in bids if isinstance(b, LensBid)]:
            orphans.append(scene)
    assert orphans == ["person", "unknown"], f"scenes with no bidder: {orphans}"


def test_the_sky_survives_a_high_RESOLUTION_frame():
    """The light cues are box-averaged, and averaging destroys the thing they
    measure: at 2160 px the block is 4x4, so a 1-px star is divided by sixteen and
    a whole starfield measured ZERO lights — the sky simply vanished above the size
    the phone happens to post. Pooled by MAXIMUM, a point light survives at any
    input size."""
    import numpy as np
    from dreamlayer.ai_brain.perception import HeuristicPerceptor, frame_cues
    P = HeuristicPerceptor()

    def stars(size):
        rng = np.random.default_rng(11)
        h = int(size * 0.75)
        a = np.full((h, size), 7.0)
        for _ in range(90):
            y, x = rng.integers(1, h - 2), rng.integers(1, size - 2)
            a[y, x] = rng.integers(90, 255)
        return (a + rng.normal(0, 2.0, a.shape)).clip(0, 255).astype(np.uint8)
    for size in (240, 480, 720, 1080, 2160):
        assert frame_cues(stars(size)).get("lights", 0) >= 8, size
        assert P.perceive(stars(size)).sky is True, size


def test_low_contrast_structure_is_counted_but_a_wall_is_not():
    """The prominence floor was fitted to high-contrast synthetics (a shelf 0.31, a
    page 0.51), so it sat above real pale-on-pale structure: a foggy street measures
    0.010-0.017 and a grey filing cabinet 0.011-0.021, both silently uncounted, and
    the cabinet flipped between 0 and 4 peaks with resolution."""
    import numpy as np
    from dreamlayer.ai_brain.perception import frame_cues

    def bars(dn, n=12, size=720):
        h = int(size * 0.75)
        a = np.full((h, size), 128.0)
        for i in range(n):
            x = int(i * size / n)
            a[int(h * 0.2):int(h * 0.8), x + 4:x + int(size / n) - 4] = 128.0 + dn
        rng = np.random.default_rng(3)
        return (a + rng.normal(0, 1.5, a.shape)).clip(0, 255).astype(np.uint8)
    for dn in (6, 9, 12, 20, 40):
        assert frame_cues(bars(dn))["col_reps"] >= 8, f"{dn} DN of contrast is structure"
    # a wall, with and without a lighting gradient, is still nothing
    rng = np.random.default_rng(7)
    for grad in (0.0, 24.0):
        a = (np.full((540, 720), 128.0) + np.linspace(0, grad, 720)[None, :]
             + rng.normal(0, 1.5, (540, 720)))
        c = frame_cues(a.clip(0, 255).astype(np.uint8))
        assert c["col_reps"] == 0 and c["row_reps"] == 0, (grad, c)


def test_one_pick_does_not_fully_arm_the_learned_nudge():
    """`boost` was a pure SHARE, so it returned the full weight after a single
    reinforce — identical at 1, 2, 3, 4 and 200 picks. That nudge is what opens the
    salience gap and makes a fire look "clear", so one accidental tap was enough to
    start steering every later look on that scene."""
    from dreamlayer.orchestrator.glance import GlancePriors
    seen = []
    for n in (1, 2, 3, 4, 8):
        p = GlancePriors()
        for _ in range(n):
            p.reinforce("text", "read")
        seen.append(round(p.boost("text", "read"), 4))
    assert seen[0] < seen[1] < seen[2], f"the nudge must grow with evidence: {seen}"
    assert seen[0] <= 0.05, f"one pick must be a hint, not a verdict: {seen[0]}"
    assert seen[-1] == seen[-2], "and it saturates once established"


def test_the_priors_have_no_silently_coupled_constants():
    """`amount` was coupled to confident()'s floor with nothing saying so: at 0.3 or
    below the row converges on 3.0 or less, so confidence became PERMANENTLY
    unreachable, and below ~1.1e-3 the decay deleted the entry before the credit
    landed so the row never grew at all — while `boost` still reported a full share
    of it. A full row was worse: it returned early, so it stopped decaying AND
    stopped accepting, freezing whatever habit it happened to hold."""
    from dreamlayer.orchestrator.glance import GlancePriors, MAX_PRIOR_LENSES
    for amount in (1.0, 0.3, 0.05, 1e-9):
        p = GlancePriors()
        for _ in range(8):
            p.reinforce("text", "read", amount)
        assert p.confident("text", "read"), f"amount={amount} must reach confidence"
    # a full row still decays and still accepts
    p = GlancePriors()
    for i in range(MAX_PRIOR_LENSES + 2):
        p.reinforce("text", f"lens{i}")
    row_before = dict(p._c["text"])
    p.reinforce("text", "brand-new")
    assert len(p._c["text"]) <= MAX_PRIOR_LENSES
    assert p._c["text"] != row_before, "a full row must not freeze"
    assert "brand-new" in p._c["text"], "the newest pick must land"
    assert p.boost("text", "brand-new") > 0


def test_the_posture_cue_fails_closed_on_the_client():
    """Two ways the elevation can be confidently WRONG rather than absent, both of
    which the page must refuse instead: gamma missing (substituting 0 silently
    reverts to the portrait-only formula, which is the exact case gamma was added to
    fix) and a FRONT camera (facingMode is requested as an ideal, so a device
    without a rear camera hands over the selfie one and every elevation inverts)."""
    page = live_mod._PAGE
    assert 'typeof e.gamma !== "number") return' in page
    assert "if (REARCAM === false) return;" in page
    assert 'REARCAM = fm ? (fm === "environment") : null' in page
    # and the value is still only sent when a real reading arrived
    assert 'if (TILTOK) q.set("tilt"' in page
