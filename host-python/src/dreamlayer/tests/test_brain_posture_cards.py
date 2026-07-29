"""The privacy shield, drawn — `PrivacyVeilCard` and `ReadyCard`.

Both were declared HUD features with no Brain-side producer. They are wired as
a PAIR because either alone is a defect:

  * the veil card alone would be suppressed by the veil it announces
    (`push_event` drops every non-`veil_ok` push while `incognito_now()`), and
  * the veil card alone is `dismiss_ms: 0` — stays until replaced — so with
    nothing to replace it the glass keeps reading "Nothing is being captured"
    after capture has resumed. That is not a cosmetic stale card; it is a false
    assurance about privacy, which is the worst error this product can make.

`ReadyCard` also had no reachable trigger at all: a push at Brain start reaches
zero subscribers, because nothing is connected yet. Its trigger is the veil
LIFTING, which is both a real Brain event and the moment the stale veil card
must be replaced.

A posture greeting on each new subscription was tried and reverted. It gave a
connecting phone the current posture, which is worth something — but a fresh
subscription yielding an EMPTY queue is a contract 21 tests across three files
encode on purpose, since it is what makes "this push reached N streams"
checkable. `test_a_new_subscription_starts_empty` pins the revert.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except Exception:
            return out


def test_a_new_subscription_starts_empty(brain):
    """The reverted greeting, pinned as a contract rather than left to be
    rediscovered. Every push-counting assertion in the suite depends on a fresh
    queue holding nothing but what the test itself caused."""
    q = brain.subscribe_events()
    assert q is not None
    assert _drain(q) == []
    brain.config.network_mode = "lan_only"
    assert _drain(brain.subscribe_events()) == [], (
        "subscribing under the veil enqueued a greeting")


def test_the_veil_card_pierces_the_veil_that_would_drop_it(brain):
    """The whole reason this needs `veil_ok=True`. With the default gate the
    card announcing the shield is suppressed BY the shield, and the wearer gets
    no indication at all that capture stopped."""
    q = brain.subscribe_events()
    brain.config.network_mode = "lan_only"
    assert brain.incognito_now() is True
    sent = brain.announce_posture(True)
    assert sent == 1, "the veil card was dropped by its own gate"
    ev = _drain(q)[0]
    assert ev["card"]["type"] == "PrivacyVeilCard"
    assert ev["safety"] is True                    # the flag that let it through


def test_lifting_the_veil_replaces_the_card_rather_than_leaving_it(brain):
    """PrivacyVeilCard never expires on its own. If nothing replaces it the
    glass keeps promising "Nothing is being captured" while the microphone is
    open again."""
    q = brain.subscribe_events()
    brain.config.network_mode = "lan_only"
    brain.announce_posture(True)
    _drain(q)
    brain.config.network_mode = "connected"
    assert brain.announce_posture(False) == 1
    assert _drain(q)[0]["card"]["type"] == "ReadyCard"


def test_the_veil_card_carries_no_captured_content(brain):
    """The stated bar for `veil_ok=True`. If this card ever grew a field that
    quoted the wearer, piercing the veil with it would leak exactly what the
    veil exists to stop."""
    from dreamlayer.hud import cards
    card = cards.privacy_veil()
    blob = repr(card)
    assert card["type"] == "PrivacyVeilCard"
    for field in ("text", "transcript", "utterance", "person", "speaker",
                  "summary", "detail", "footer"):
        assert field not in card, f"{field} could carry captured content"
    assert "Nothing is being captured" in blob


# --- the transition, through the real route ---------------------------------

def test_the_config_route_announces_only_on_a_transition(brain):
    """The panel saves the whole config on every switch, so re-POSTing the same
    posture must not re-push the card."""
    q = brain.subscribe_events()
    brain.apply_config({"network_mode": "lan_only"})
    before = brain.incognito_now()
    brain.apply_config({"network_mode": "lan_only"})
    assert brain.incognito_now() == before
    # apply_config alone pushes nothing — the route owns the announcement, and
    # this asserts the *state* it reads is stable across a repeat save.
    assert _drain(q) == []


def test_quiet_hours_mean_the_effective_posture_not_the_flag(brain):
    """A patch clearing lan_only INSIDE quiet hours does not lift the shield.
    Reading `config.lan_only` instead of `incognito_now()` would announce a
    veil-down that never happened."""
    import datetime as _dt
    hour = _dt.datetime.now().hour
    brain.config.quiet_hours = f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"
    brain.config.network_mode = "lan_only"
    assert brain.incognito_now() is True
    brain.config.network_mode = "connected"
    assert brain.incognito_now() is True, "quiet hours still veil the Brain"
