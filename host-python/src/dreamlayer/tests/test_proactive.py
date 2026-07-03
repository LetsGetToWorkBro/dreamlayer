"""test_proactive.py — the right card at the right moment.

The anticipation engine ties place + time + person into anticipatory cards,
ranks them, de-dupes with a cooldown, and is silenced by the Privacy Veil."""
from __future__ import annotations

from dreamlayer.orchestrator.anticipation import (
    AnticipationEngine, Context, Anchor, Event, Commitment,
)
from dreamlayer.tests.test_integration_dream_suite import FakeBridge
from dreamlayer.orchestrator.orchestrator import Orchestrator


def test_event_person_place_all_fire_ranked():
    eng = AnticipationEngine()
    ctx = Context(
        now=1000.0,
        place="4th and Alder north rack",
        person="Marcus",
        events=[Event("Standup", ts=1000.0 + 8 * 60)],            # in 8 min
        anchors=[Anchor("bike", "4th and Alder north rack")],
        commitments=[Commitment("Marcus", "you owe the signed lease")],
    )
    cues = eng.tick(ctx)
    assert [c.kind for c in cues] == ["event", "person", "place"]  # ranked
    assert cues[0].card["type"] == "UpcomingCard" and cues[0].card["minutes"] == 8
    assert "lease" in cues[1].card["detail"]                       # commitment
    assert cues[2].card["primary"] == "bike"                       # what you left


def test_far_off_event_does_not_fire():
    eng = AnticipationEngine()
    assert eng.tick(Context(now=0.0, events=[Event("Lunch", ts=3 * 3600)])) == []


def test_cooldown_prevents_nagging():
    eng = AnticipationEngine(cooldown_s=300)
    assert len(eng.tick(Context(now=1000.0, person="Priya"))) == 1
    assert eng.tick(Context(now=1060.0, person="Priya")) == []     # 1 min later: hushed
    assert len(eng.tick(Context(now=1400.0, person="Priya"))) == 1  # past cooldown: ok


def test_veil_silences_anticipation():
    orc = Orchestrator(FakeBridge())
    assert orc.anticipate_tick(Context(now=1000.0, person="Marcus"))  # fires normally
    orc.privacy.pause()                                             # raise the veil
    assert orc.anticipate_tick(Context(now=2000.0, person="Marcus")) == []


def test_toggle_silences_anticipation():
    orc = Orchestrator(FakeBridge())
    orc.set_anticipation(False)
    assert orc.anticipate_tick(Context(now=1000.0, person="Marcus")) == []
    orc.set_anticipation(True)
    assert orc.anticipate_tick(Context(now=2000.0, person="Marcus"))
