"""test_user_model.py — the Juno learns you.

A light on-device profile: the topics you return to, who you talk with, what you
tell it to remember, and what to call you. Built passively from your own lines
and from explicit teaches; it adapts the persona and survives a restart.
"""
from __future__ import annotations

import os

from dreamlayer.orchestrator.user_model import UserModel
from dreamlayer.orchestrator import persona
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _replies(br):
    return [f for f in br.raw if f.get("t") == "card" and f.get("type") == "JunoReplyCard"]


# -- passive interests --------------------------------------------------------

def test_learns_topics_from_your_own_words():
    u = UserModel()
    u.observe("The telescope tracked Saturn beautifully last night.")
    u.observe("I want a better telescope for Saturn.")
    assert "telescope" in u.interests()
    assert "saturn" in u.interests()


def test_other_peoples_words_are_not_your_interests():
    u = UserModel()
    u.observe("Cryptocurrency is the future.", speaker="Dana")
    assert "cryptocurrency" not in u.interests()


def test_tracks_who_you_talk_with():
    u = UserModel()
    u.note_person("Marcus"); u.note_person("Marcus"); u.note_person("Priya")
    assert u.top_people()[0] == "Marcus"


# -- explicit teaching --------------------------------------------------------

def test_learns_your_name():
    u = UserModel()
    assert u.learn("Call me Sam")["kind"] == "name"
    assert u.address() == "Sam"


def test_learns_a_preference():
    u = UserModel()
    got = u.learn("Remember that I prefer aisle seats")
    assert got["kind"] == "preference" and "aisle seats" in got["value"]
    assert any("aisle" in p for p in u.preferences())


def test_small_talk_teaches_nothing():
    u = UserModel()
    assert u.learn("What's the weather like?") is None


# -- persistence across a restart ---------------------------------------------

def test_profile_survives_a_restart(tmp_path):
    p = os.path.join(tmp_path, "usermodel.json")
    a = UserModel(p)
    a.learn("Call me Sam")
    a.observe("I love astronomy and telescopes.")
    b = UserModel(p)                       # a fresh process reads the same file
    assert b.address() == "Sam"
    assert "astronomy" in b.interests()


# -- persona adapts -----------------------------------------------------------

def test_greeting_warms_with_your_name():
    assert persona.greeting() == "I'm here."
    assert persona.greeting("Sam") == "I'm here, Sam."


# -- end to end through the orchestrator --------------------------------------

def test_juno_learns_your_name_on_command():
    br = FakeBridge()
    orc = Orchestrator(br)
    out = orc.ask_juno("Call me Sam")
    assert out["intent"] == "learn" and out["executed"]
    assert orc.user.address() == "Sam"
    assert "Sam" in _replies(br)[-1]["primary"]
    assert orc.juno_greeting() == "I'm here, Sam."


def test_orchestrator_builds_interests_from_captions():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.ingest_caption("I've been reading about volcanoes all week.", speaker="", ts=1.0)
    orc.ingest_caption("Volcanoes near Iceland fascinate me.", speaker="", ts=2.0)
    snap = orc.user_snapshot()
    assert "volcanoes" in snap["interests"]
