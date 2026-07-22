"""The Live Lens event bus: the Brain PUSHES ambient cards to connected phones
over SSE — the half of the HUD that isn't a reply to a look (a sound-safety tap,
the morning brief, a memory nudge). These pin the bus + the sound-safety wiring
deterministically (no server, no audio deps):

  * push_event fans a card out to every subscriber,
  * it is VEIL-GATED — an ambient push is suppressed while incognito, but a
    categorical safety alert (a smoke alarm) pierces the veil,
  * the subscriber count is capped (an SSE stream holds a worker thread),
  * a watch-out sound → a HarkCard is pushed; a non-attention sound → nothing.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain, MAX_EVENT_SUBS
from dreamlayer.ai_brain.server.ear import EarHost


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


# --- the bus -----------------------------------------------------------------

def test_push_event_fans_out_to_every_subscriber(brain):
    q1 = brain.subscribe_events()
    q2 = brain.subscribe_events()
    n = brain.push_event("hark", {"type": "HarkCard", "primary": "smoke alarm"})
    assert n == 2
    e1 = q1.get_nowait()
    e2 = q2.get_nowait()
    assert e1["kind"] == "hark" and e1["card"]["primary"] == "smoke alarm"
    assert e2 == e1


def test_ambient_push_is_suppressed_under_the_veil(brain):
    brain.config.network_mode = "lan_only"           # incognito
    q = brain.subscribe_events()
    assert brain.push_event("brief", {"type": "MorningBriefCard"}) == 0
    assert q.empty()


def test_a_safety_alert_pierces_the_veil(brain):
    brain.config.network_mode = "lan_only"           # incognito
    q = brain.subscribe_events()
    assert brain.push_event("hark", {"type": "HarkCard"}, veil_ok=True) == 1
    assert q.get_nowait()["kind"] == "hark"


def test_subscriber_count_is_capped(brain):
    qs = [brain.subscribe_events() for _ in range(MAX_EVENT_SUBS)]
    assert all(q is not None for q in qs)
    assert brain.subscribe_events() is None          # over the cap → refused
    brain.unsubscribe_events(qs[0])
    assert brain.subscribe_events() is not None      # a slot freed up


def test_unsubscribe_stops_delivery(brain):
    q = brain.subscribe_events()
    brain.unsubscribe_events(q)
    assert brain.push_event("hark", {"type": "HarkCard"}, veil_ok=True) == 0


def test_push_event_drops_a_full_queue_without_blocking(brain):
    q = brain.subscribe_events()
    for _ in range(q.maxsize):                        # fill it
        q.put_nowait({"kind": "x"})
    # a further push must not block or raise — it just doesn't reach this client
    assert brain.push_event("hark", {"type": "HarkCard"}, veil_ok=True) == 0


# --- the sound-safety wire (ear → bus → HarkCard) ----------------------------

def test_a_watchout_sound_pushes_an_urgent_hark_card(brain):
    ear = EarHost(brain)
    q = brain.subscribe_events()
    ear.note_acoustic_context([("smoke alarm", 0.9)])    # a watch-out
    ev = q.get_nowait()
    assert ev["kind"] == "hark"
    assert ev["card"]["type"] == "HarkCard"
    assert ev["card"]["importance"] == "urgent"


def test_a_plain_listen_sound_does_not_pierce_the_veil(brain):
    brain.config.network_mode = "lan_only"           # incognito
    ear = EarHost(brain)
    q = brain.subscribe_events()
    ear.note_acoustic_context([("doorbell", 0.9)])       # a 'listen', not a watch-out
    assert q.empty()                                     # suppressed under the shield


def test_a_non_attention_sound_pushes_nothing(brain):
    ear = EarHost(brain)
    q = brain.subscribe_events()
    ear.note_acoustic_context([("music", 0.95)])         # not an attention sound
    assert q.empty()
    ear.note_acoustic_context([])                        # no tags at all
    assert q.empty()
