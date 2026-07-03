"""test_focus_and_cues.py — Focus mode and the proactive-cue picker.

Focus turns the interruptions down (anticipation, captions, message pop-ups)
for a stretch without pausing capture — distinct from Incognito. The cue picker
lets you keep some anticipatory kinds and mute others.
"""
from __future__ import annotations

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.anticipation import (
    AnticipationEngine, Context, Event, Anchor,
)
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _cards(br):
    return [f for f in br.raw if f.get("t") == "card"]


# -- cue picker ---------------------------------------------------------------

def test_engine_mutes_a_disabled_cue_kind():
    eng = AnticipationEngine()
    eng.set_kind("place", False)
    ctx = Context(now=1000.0, place="north rack",
                  anchors=[Anchor("bike", "north rack")],
                  person="Marcus")
    kinds = [c.kind for c in eng.tick(ctx)]
    assert "person" in kinds and "place" not in kinds     # place muted, person kept


def test_orchestrator_cue_toggle_roundtrips():
    orc = Orchestrator(FakeBridge())
    assert orc.cue_kinds() == {"event": True, "person": True, "place": True}
    orc.set_cue("event", False)
    assert orc.cue_kinds()["event"] is False
    # a soon event no longer fires; a person still does
    ctx = Context(now=0.0, events=[Event("Standup", ts=5 * 60)], person="Priya")
    kinds = [c.kind for c in orc.anticipate_tick(ctx)]
    assert kinds == ["person"]


# -- focus mode ---------------------------------------------------------------

def test_focus_silences_anticipation_but_capture_continues():
    orc = Orchestrator(FakeBridge())
    orc.set_focus(25)
    assert orc.focus_active()
    assert orc.anticipate_tick(Context(now=0.0, person="Marcus")) == []
    # capture is NOT paused (unlike incognito) — a caption is still recorded
    assert orc.ingest_caption("still recording", speaker="Marcus") is not None
    orc.clear_focus()
    assert not orc.focus_active()
    assert orc.anticipate_tick(Context(now=0.0, person="Marcus"))   # fires again


def test_focus_holds_back_captions_on_the_hud():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_focus(25)
    orc.ingest_caption("keep it down", speaker="Priya")
    assert _cards(br) == []                        # nothing flashed while focused
    assert len(orc.conversation) == 1              # but the ledger still has it


def test_focus_suppresses_message_popups():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_focus(25)
    feed = [{"channel": "imessage", "who": "Marcus", "from_me": False,
             "text": "you around?", "ts": 100.0}]
    assert orc.poll_messages(feed) == []           # no pop-up during focus
    assert _cards(br) == []


def test_focus_expires_on_its_own():
    orc = Orchestrator(FakeBridge())
    orc.set_focus(0)                               # 0 minutes → already elapsed
    assert not orc.focus_active()
