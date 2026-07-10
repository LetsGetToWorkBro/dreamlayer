"""test_attention.py — when Juno decides to say "Listen!" / "Watch out!"

The policy reads live context and raises the right interruption at the right
moment, ranks urgency, and — crucially — never nags.
"""
from __future__ import annotations

from dreamlayer.orchestrator.attention import AttentionPolicy, Alert
from dreamlayer.orchestrator.anticipation import Context, Event, Anchor, Commitment
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _harks(br):
    return [f for f in br.raw if f.get("t") == "card" and f.get("type") == "HarkCard"]


# -- the policy in isolation --------------------------------------------------

def test_time_critical_event_is_a_watchout():
    pol = AttentionPolicy()
    ctx = Context(now=1000.0, events=[Event("gate B12", ts=1000.0 + 5 * 60, place="Terminal 2")])
    (a,) = pol.evaluate(ctx)
    assert a.level == "watchout" and "5 min to gate B12" in a.clue and "Terminal 2" in a.detail


def test_person_you_owe_in_view_is_a_listen():
    pol = AttentionPolicy()
    ctx = Context(now=1000.0, person="Marcus",
                  commitments=[Commitment("Marcus", "the signed lease")])
    (a,) = pol.evaluate(ctx)
    assert a.level == "listen" and "You owe Marcus" in a.clue and "lease" in a.clue


def test_leaving_a_place_you_left_something_is_a_listen():
    pol = AttentionPolicy()
    anch = [Anchor("bike", "4th & Alder rack")]
    # tick 1: you're at the rack (nothing yet — no departure)
    assert pol.evaluate(Context(now=1000.0, place="4th & Alder rack", anchors=anch)) == []
    # tick 2: you've walked off → Juno speaks up
    (a,) = pol.evaluate(Context(now=1100.0, place="on Alder St", anchors=anch))
    assert a.level == "listen" and "leaving your bike" in a.clue


def test_commitment_about_to_slip_is_a_listen():
    pol = AttentionPolicy()
    soon = Commitment("Priya", "send the invoice", due_ts=1000.0 + 3600)
    (a,) = pol.evaluate(Context(now=1000.0, commitments=[soon]))
    assert a.level == "listen" and a.clue == "send the invoice" and "Priya" in a.detail


def test_watchout_outranks_listen():
    pol = AttentionPolicy()
    ctx = Context(now=1000.0, person="Marcus",
                  events=[Event("standup", ts=1000.0 + 60)],
                  commitments=[Commitment("Marcus", "the lease")])
    alerts = pol.evaluate(ctx)
    assert alerts[0].level == "watchout"          # urgency first


def test_marking_prevents_nagging():
    pol = AttentionPolicy(per_key_cooldown_s=1800.0)
    ctx = Context(now=1000.0, person="Marcus", commitments=[Commitment("Marcus", "the lease")])
    (a,) = pol.evaluate(ctx)
    pol.mark(a.key, 1000.0)
    assert pol.evaluate(Context(now=1300.0, person="Marcus",
                                commitments=[Commitment("Marcus", "the lease")])) == []
    # past the cooldown it may speak again
    assert pol.evaluate(Context(now=1000.0 + 2000, person="Marcus",
                                commitments=[Commitment("Marcus", "the lease")]))


# -- wired through the orchestrator + hark ------------------------------------

def test_attention_tick_speaks_the_top_alert_and_wont_repeat():
    br = FakeBridge()
    orc = Orchestrator(br)
    ctx = Context(now=1000.0, person="Marcus", commitments=[Commitment("Marcus", "the lease")])
    card = orc.attention_tick(ctx)
    assert card and card["type"] == "HarkCard" and card["earcon"] == "hark"   # listen
    # same moment again → hushed (marked + hark cooldown)
    assert orc.attention_tick(Context(now=1030.0, person="Marcus",
                                      commitments=[Commitment("Marcus", "the lease")])) is None
    assert len(_harks(br)) == 1


def test_watchout_tick_is_urgent_and_pierces_focus():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_focus(25)                              # interruptions down…
    ctx = Context(now=1000.0, events=[Event("your flight", ts=1000.0 + 4 * 60, place="Gate 9")])
    card = orc.attention_tick(ctx)
    assert card and card["earcon"] == "hark_urgent"   # …but a watch-out still speaks


def test_veil_silences_attention():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.privacy.pause()
    ctx = Context(now=1000.0, person="Marcus", commitments=[Commitment("Marcus", "the lease")])
    assert orc.attention_tick(ctx) is None and _harks(br) == []


def test_toggle_off_silences_attention():
    orc = Orchestrator(FakeBridge())
    orc.set_attention(False)
    ctx = Context(now=1000.0, events=[Event("gate", ts=1000.0 + 60)])
    assert orc.attention_tick(ctx) is None
