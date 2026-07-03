"""test_hark.py — Oracle's "Listen!" (Navi) proactive cue + the earcon slot.

Oracle taps you on the shoulder with one thing worth hearing, plays its own
attention sound, and never nags: rate-limited, Veil-silenced, Focus-aware.
"""
from __future__ import annotations

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.hud import cards, audio
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _harks(br):
    return [f for f in br.raw if f.get("t") == "card" and f.get("type") == "HarkCard"]


# -- the card -----------------------------------------------------------------

def test_hark_card_carries_clue_and_earcon():
    c = cards.hark("Marcus is 2 min away — you owe him the lease.", "from your chat")
    assert c["type"] == "HarkCard" and c["eyebrow"] == "LISTEN"
    assert "Marcus" in c["primary"] and c["detail"] == "from your chat"
    assert c["earcon"] == "hark" and c["flash"] is True


def test_urgent_hark_is_stronger():
    normal, urgent = cards.hark("x"), cards.hark("x", importance="urgent")
    assert urgent["dismiss_ms"] > normal["dismiss_ms"]
    assert urgent["haptic"] == "double" and normal["haptic"] == "tick"


# -- the orchestrator behaviour ----------------------------------------------

def test_hark_fires_then_respects_cooldown():
    br = FakeBridge()
    orc = Orchestrator(br)
    assert orc.hark("first clue", now=1000.0) is not None
    assert orc.hark("second clue", now=1030.0) is None       # within cooldown
    assert orc.hark("third clue", now=1000.0 + 200) is not None
    assert len(_harks(br)) == 2


def test_veil_silences_hark():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.privacy.pause()
    assert orc.hark("secret clue") is None and _harks(br) == []


def test_focus_holds_normal_hark_but_urgent_pierces():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_focus(25)
    assert orc.hark("just a nudge", now=1.0) is None          # normal held during focus
    assert orc.hark("this matters", importance="urgent", now=100.0) is not None


# -- the custom earcon slot ---------------------------------------------------

def test_resolve_clip_finds_your_dropped_sound(tmp_path):
    assert audio.resolve_clip(tmp_path, "hark") is None       # nothing dropped yet
    d = tmp_path / "sounds"; d.mkdir()
    (d / "hark.mp3").write_bytes(b"ID3fake")
    got = audio.resolve_clip(tmp_path, "hark")
    assert got is not None and got.name == "hark.mp3"
    assert audio.resolve_clip(tmp_path, "not-an-earcon") is None
    assert "hark" in audio.earcon_ids()
