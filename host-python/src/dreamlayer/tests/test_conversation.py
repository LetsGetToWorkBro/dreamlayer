"""test_conversation.py — the spoken-word ledger and what it powers.

Live captions, day-recall ("what did they say about X"), rewind-my-day, and the
person dossier on greeting — all off one bounded, Veil-gated ledger.
"""
from __future__ import annotations

from dreamlayer.orchestrator.conversation import ConversationLedger, Utterance
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# -- the ledger in isolation --------------------------------------------------

def test_captions_return_the_recent_tail_oldest_first():
    led = ConversationLedger()
    for i in range(10):
        led.add(f"line {i}", speaker="Marcus", ts=1000.0 + i)
    tail = led.captions(3)
    assert [u.text for u in tail] == ["line 7", "line 8", "line 9"]


def test_empty_lines_are_ignored():
    led = ConversationLedger()
    assert led.add("   ") is None and len(led) == 0


def test_recall_matches_topic_keywords_newest_first():
    led = ConversationLedger()
    led.add("we should sign the lease", speaker="Marcus", ts=1.0)
    led.add("lunch was great", speaker="Priya", ts=2.0)
    led.add("the lease renewal is due Friday", speaker="Marcus", ts=3.0)
    hits = led.recall("lease")
    assert [u.ts for u in hits] == [3.0, 1.0]          # newest first, lunch excluded


def test_recall_can_scope_to_one_person():
    led = ConversationLedger()
    led.add("the budget looks tight", speaker="Priya", ts=1.0)
    led.add("the budget is fine", speaker="Marcus", ts=2.0)
    hits = led.recall("budget", person="Priya")
    assert len(hits) == 1 and hits[0].speaker == "Priya"


def test_timeline_groups_by_hour_with_people_and_samples():
    led = ConversationLedger()
    day = 1_700_000_000.0
    day = day - (day % 86400)                          # midnight-aligned
    led.add("morning standup", speaker="Marcus", ts=day + 9 * 3600 + 10)
    led.add("coffee chat", speaker="Priya", ts=day + 9 * 3600 + 800)
    led.add("afternoon sync", speaker="Marcus", ts=day + 14 * 3600)
    tl = led.timeline(day)
    assert [b["hour"] for b in tl] == [9, 14]
    nine = tl[0]
    assert nine["count"] == 2 and "Marcus" in nine["people"] and "Priya" in nine["people"]
    assert len(nine["lines"]) == 2


def test_dossier_summarizes_a_person():
    led = ConversationLedger()
    led.add("the lease is ready to sign", speaker="Marcus", ts=1000.0)
    led.add("did you send the lease yet", speaker="Marcus", ts=2000.0)
    d = led.dossier("Marcus", now=2000.0 + 3600)
    assert d["known"] and d["exchanges"] == 2
    assert d["last_seen_ago"] == "1 hr ago"
    assert "lease" in d["topics"]
    assert d["last_line"] == "did you send the lease yet"


def test_dossier_unknown_person():
    assert ConversationLedger().dossier("Nobody")["known"] is False


# -- wired through the orchestrator ------------------------------------------

def _cards(bridge):
    return [f for f in bridge.raw if f.get("t") == "card"]


def test_ingest_caption_stores_and_flashes_on_glasses():
    br = FakeBridge()
    orc = Orchestrator(br)
    u = orc.ingest_caption("lock the lease by Friday", speaker="Marcus")
    assert isinstance(u, Utterance)
    caps = _cards(br)
    assert caps and caps[-1]["type"] == "SpokenCaptionCard"
    assert orc.live_captions(1)[0].text == "lock the lease by Friday"


def test_veil_silences_caption_capture():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.privacy.pause()
    assert orc.ingest_caption("secret", speaker="Marcus") is None
    assert _cards(br) == [] and len(orc.conversation) == 0


def test_captions_toggle_keeps_ledger_but_hides_hud():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_captions(False)
    u = orc.ingest_caption("still recorded", speaker="Priya")
    assert u is not None                               # still in the ledger
    assert _cards(br) == []                            # but not on the glasses


def test_recall_is_incognito_friendly_but_pause_holds_it():
    # Pinned privacy contract: incognito blocks capture/writes, NOT recall —
    # you can still ask what you already know. The full pause veil is deaf and
    # blind, so even an explicit query is held until you lift it.
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.ingest_caption("the lease renewal is Friday", speaker="Marcus", ts=100.0)
    orc.set_incognito(True)
    assert orc.recall_conversation("lease")            # incognito: recall works
    orc.set_incognito(False)
    orc.privacy.pause()                                # full veil down
    assert orc.recall_conversation("lease") == []      # pause holds recall
    assert orc.rewind_day() == []


def test_greet_surfaces_a_known_person_dossier():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.ingest_caption("send me the signed lease", speaker="Marcus")
    card = orc.greet("Marcus")
    assert card and card["type"] == "PersonDossierCard" and card["person"] == "Marcus"


def test_greet_unknown_person_is_silent():
    br = FakeBridge()
    orc = Orchestrator(br)
    assert orc.greet("Stranger") is None
