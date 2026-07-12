"""test_wake_and_scrub.py — brief-to-glasses at wake + scrubbable rewind.

Putting the Halo on flashes the brief the Brain already prepared; the day's
moments become a physical forward/back scrub on the glasses.
"""
from __future__ import annotations

import time

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.hud import cards
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _cards(br, event=None):
    out = [f for f in br.raw if f.get("t") == "card"]
    return out


# -- brief to the glasses at wake --------------------------------------------

def _brief_slots(br, fid):
    slots = {}
    for f in br.raw:
        if f.get("t") == "figment_text" and f.get("id") == fid:
            slots[f.get("slot", "")] = f.get("text")
    return slots


def test_wake_streams_the_latest_brief_into_a_figment():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.brain_url = "http://mac.local:7777"          # paired
    fake_get = lambda url, token="": {
        "text": "Two meetings; lease due Friday.",
        "bullets": ["Standup 9am", "1 new text"], "ts": time.time()}
    out = orc.wake(http_get=fake_get)
    assert out and out["surface"] == "figment"
    # the morning-brief figment was put + swapped onto the stage
    assert any(f.get("t") == "figment_put" for f in br.raw)
    assert orc._active_figment == out["figment_id"]
    # and the day's synthesis + first points filled the named slots
    slots = _brief_slots(br, out["figment_id"])
    assert "lease" in slots["synthesis"]
    assert slots["point1"] == "Standup 9am" and slots["point2"] == "1 new text"
    assert _cards(br) == []                           # no card on this path anymore


def test_wake_is_silent_without_a_brief_or_brain():
    br = FakeBridge()
    orc = Orchestrator(br)
    assert orc.wake(http_get=lambda u, t="": {}) is None    # no brain_url paired
    orc.brain_url = "http://mac.local:7777"
    assert orc.wake(http_get=lambda u, t="": {}) is None    # brain up, no brief yet
    assert _cards(br) == []


def test_wake_is_veil_gated():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.brain_url = "http://mac.local:7777"
    orc.privacy.pause()
    assert orc.wake(http_get=lambda u, t="": {"text": "x", "ts": 1}) is None


def test_morning_brief_card_shape():
    c = cards.morning_brief("A busy day.", ["one", "two", "three", "four"])
    assert c["type"] == "MorningBriefCard"
    assert c["bullets"] == ["one", "two", "three"]      # capped at 3
    assert c["detail"] == "one" and c["footer"] == "two"


# -- scrubbable rewind on the glasses ----------------------------------------

def _seed_day(orc):
    # drop a few semantic events into the ring across the last hour
    from dreamlayer.pipelines.ingest import MemoryEvent
    now = time.time()
    for i, s in enumerate(["coffee with Priya", "standup", "lease call with Marcus"]):
        orc.ring.append(MemoryEvent(kind="conversation", summary=s, confidence=0.8),
                        ts=now - (3 - i) * 600)
    return now


def test_rewind_scrub_flashes_and_navigates_on_glasses():
    br = FakeBridge()
    orc = Orchestrator(br)
    _seed_day(orc)
    first = orc.rewind_scrub()
    assert first and first["type"] == "TimeScrubNodeCard"
    assert _cards(br)[-1]["type"] == "TimeScrubNodeCard"     # flashed on the glasses
    # scrubbing back moves toward the past and re-renders
    before = len(_cards(br))
    node = orc.scrub("back")
    assert node is not None and len(_cards(br)) == before + 1


def test_scrub_without_a_session_is_silent():
    orc = Orchestrator(FakeBridge())
    assert orc.scrub("back") is None
