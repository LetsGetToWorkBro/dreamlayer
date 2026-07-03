"""test_message_notify.py — texts/emails pop up on the glasses.

The Mac mini Brain is the bridge; the hub polls its message feed and the
orchestrator turns new *incoming* messages into HUD cards — silenced by the
Privacy Veil, toggleable, and idempotent."""
from __future__ import annotations

from dreamlayer.hud import cards
from dreamlayer.tests.test_integration_dream_suite import FakeBridge
from dreamlayer.orchestrator.orchestrator import Orchestrator


def _orc():
    return Orchestrator(FakeBridge())


def _cards(orc):
    return [f for f in orc.bridge.raw if f.get("t") == "card"]


FEED = [
    {"channel": "imessage", "who": "Marcus", "from_me": False, "text": "you around?", "ts": 10.0},
    {"channel": "imessage", "who": "Me", "from_me": True, "text": "one sec", "ts": 11.0},
    {"channel": "email", "who": "landlord@birch.co", "from_me": False,
     "subject": "Renewal", "text": "sign by Friday", "ts": 12.0},
]


def test_new_incoming_messages_pop_up():
    orc = _orc()
    sent = orc.poll_messages(FEED)
    # the two incoming ones pop; the one I sent does not
    assert [c["primary"] for c in sent] == ["Marcus", "landlord@birch.co"]
    assert all(c["type"] == "MessageCard" for c in sent)
    assert _cards(orc)                          # they reached the glasses


def test_polling_is_idempotent():
    orc = _orc()
    orc.poll_messages(FEED)
    again = orc.poll_messages(FEED)             # same feed, nothing newer
    assert again == []
    # a genuinely newer message does pop
    newer = FEED + [{"channel": "imessage", "who": "Priya", "from_me": False,
                     "text": "here!", "ts": 20.0}]
    popped = orc.poll_messages(newer)
    assert [c["primary"] for c in popped] == ["Priya"]


def test_toggle_and_veil_silence_popups():
    orc = _orc()
    orc.set_message_notifications(False)
    assert orc.poll_messages(FEED) == []        # off → nothing flashes
    # but the seen-watermark still advances, so turning it back on doesn't
    # dump the backlog
    orc.set_message_notifications(True)
    assert orc.poll_messages(FEED) == []


def test_texts_and_emails_toggle_independently():
    orc = _orc()
    orc.set_email_notifications(False)          # emails off, texts still on
    sent = orc.poll_messages(FEED)
    assert [c["primary"] for c in sent] == ["Marcus"]   # only the text popped
    # now the reverse on a fresh feed
    orc2 = _orc()
    orc2.set_text_notifications(False)
    sent2 = orc2.poll_messages(FEED)
    assert [c["primary"] for c in sent2] == ["landlord@birch.co"]  # only email


def test_email_popup_uses_brain_summary_when_present():
    orc = _orc()
    feed = [{"channel": "email", "who": "a@b.co", "from_me": False,
             "subject": "Renewal", "text": "a very long body " * 40,
             "summary": "Sign the renewal by Friday.", "ts": 30.0}]
    sent = orc.poll_messages(feed)
    assert sent[0]["detail"] == "Sign the renewal by Friday."


def test_email_card_carries_subject():
    card = cards.message_notification("a@b.co", "Renewal — sign by Friday", "email")
    assert card["channel"] == "email" and card["headline"] == "Mail"
    assert "reply" in card["actions"]


def test_auto_poll_fetches_and_flashes():
    orc = _orc()
    # no Mac mini paired → nothing to poll (the Mac is the message bridge)
    assert orc.poll_messages_once(lambda url, tok: {"items": FEED}) == []
    # pair a Mac mini, then a poll flashes the new incoming messages
    orc.connect_mac_mini(True)
    orc.brain_url, orc.brain_token = "http://mac.local:7777", "tok"
    seen = {}

    def http_get(url, token):
        seen["url"], seen["token"] = url, token
        return {"items": FEED}

    sent = orc.poll_messages_once(http_get)
    assert [c["primary"] for c in sent] == ["Marcus", "landlord@birch.co"]
    assert seen["url"].endswith("/dreamlayer/messages/recent") and seen["token"] == "tok"
    # the background loop starts + stops cleanly
    orc.start_message_polling(interval=0.05, http_get=http_get)
    orc.stop_message_polling()
