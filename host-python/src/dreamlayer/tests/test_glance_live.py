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
    assert lenses <= {"taste", "rosetta", "read", "math", "juno"}
