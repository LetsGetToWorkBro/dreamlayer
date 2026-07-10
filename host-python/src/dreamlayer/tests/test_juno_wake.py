"""test_juno_wake.py — "Hey Juno", multimodal activation, and the
listening feedback that tells you it heard you.
"""
from __future__ import annotations

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.voice import detect_wake, strip_wake, ASSISTANT_NAME
from dreamlayer.hud import cards
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _cards(br):
    return [f for f in br.raw if f.get("t") == "card"]


# -- the wake grammar ---------------------------------------------------------

def test_detect_wake_hey_juno_and_remainder():
    assert detect_wake("Hey Juno, what's my day?") == (True, "what's my day?")
    assert detect_wake("juno") == (True, "")
    assert detect_wake("okay juno brief me") == (True, "brief me")
    # not addressed / a word that merely contains the name
    assert detect_wake("the juno of Delphi") == (False, "the juno of Delphi")
    assert detect_wake("what did Marcus need") == (False, "what did Marcus need")
    assert ASSISTANT_NAME == "Juno"
    assert strip_wake("Hey Juno, brief me") == "brief me"      # back-compat helper


# -- hear(): wake → command, and continuous-conversation follow-ups ----------

def test_hear_wakes_then_runs_the_command():
    br = FakeBridge()
    orc = Orchestrator(br)
    out = orc.hear("Hey Juno, brief me")
    assert out["intent"] == "brief"
    assert _cards(br)[0]["type"] == "ListeningCard"              # showed it's listening
    assert orc.juno_listening()                                # session open


def test_bare_wake_just_listens():
    orc = Orchestrator(FakeBridge())
    assert orc.hear("Hey Juno")["intent"] == "listening"
    assert orc.juno_listening()


def test_follow_up_needs_no_wake_word_during_session():
    orc = Orchestrator(FakeBridge())
    orc.hear("Hey Juno")                                       # opens the session
    out = orc.hear("what did Marcus need")                       # no wake word
    assert out["intent"] == "recall"


def test_not_addressed_when_asleep_is_idle():
    orc = Orchestrator(FakeBridge())
    assert orc.hear("what did Marcus need") == {"intent": "idle"}
    assert not orc.juno_listening()


def test_session_expires():
    orc = Orchestrator(FakeBridge())
    orc.hear("Hey Juno", now=1000.0)
    assert orc.juno_listening(now=1005.0)
    assert not orc.juno_listening(now=1000.0 + orc.juno_session_s + 1)


# -- multimodal activation (tap / gaze / raise) ------------------------------

def test_activate_by_tap_opens_listening():
    br = FakeBridge()
    orc = Orchestrator(br)
    card = orc.activate("tap")
    assert card and card["type"] == "ListeningCard" and card["source"] == "tap"
    assert orc.juno_listening()
    # after a non-voice wake, the next line is a command without a wake word
    assert orc.hear("brief me")["intent"] == "brief"


def test_disabled_wake_source_does_nothing():
    orc = Orchestrator(FakeBridge())
    orc.set_wake_source("gaze", False)
    assert orc.activate("gaze") is None and not orc.juno_listening()


def test_voice_wake_can_be_disabled():
    orc = Orchestrator(FakeBridge())
    orc.set_wake_source("voice", False)
    assert orc.hear("Hey Juno, brief me") == {"intent": "idle"}


# -- listening feedback toggles ----------------------------------------------

def test_feedback_toggles_shape_the_cue():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_wake_feedback("audio", False)
    orc.set_wake_feedback("haptic", False)
    orc.begin_listening("voice")
    c = _cards(br)[-1]
    assert c["earcon"] == "" and c["haptic"] == ""              # silenced cues
    assert c["pulse"] is True                                    # ring still pulses


def test_visual_off_shows_no_card_but_still_listens():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_wake_feedback("visual", False)
    orc.begin_listening("voice")
    assert _cards(br) == [] and orc.juno_listening()


def test_listening_card_shape():
    c = cards.listening("raise")
    assert c["type"] == "ListeningCard" and c["primary"] == "Listening…"
    assert c["eyebrow"] == "JUNO" and "raise" in c["detail"]
    assert c["dismiss_ms"] == 0
