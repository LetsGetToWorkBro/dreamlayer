"""test_hark.py — Juno's "Listen!" (Navi) proactive cue + the earcon slot.

Juno taps you on the shoulder with one thing worth hearing, plays its own
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


# -- earcon families + rotation + custom clips -------------------------------

def test_hark_card_uses_the_right_family():
    assert cards.hark("x")["earcon"] == "hark"                 # → listen family
    assert cards.hark("x", importance="urgent")["earcon"] == "hark_urgent"  # → watch-out


def test_pick_variant_avoids_immediate_repeat():
    # a two-variant family should alternate, never the same twice in a row
    seen = [audio.pick_variant("chime") for _ in range(6)]
    assert set(seen) <= set(audio.FAMILIES["chime"])
    assert all(seen[i] != seen[i + 1] for i in range(len(seen) - 1))
    assert audio.pick_variant("not-an-earcon") is None


def test_resolve_and_present_variants(tmp_path):
    assert audio.present_variants(tmp_path, "hark") == []      # nothing dropped yet
    d = tmp_path / "sounds"; d.mkdir()
    (d / "listen1.mp3").write_bytes(b"ID3fake")                # one of the two variants
    assert audio.resolve_clip(tmp_path, "listen1") is not None
    assert audio.present_variants(tmp_path, "hark") == ["listen1"]
    assert "hark" in audio.earcon_ids() and "listen1" in audio.variants("hark")
