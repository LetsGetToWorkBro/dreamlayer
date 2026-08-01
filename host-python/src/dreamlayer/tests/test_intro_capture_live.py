"""Name Capture on the Brain — "Hi, I'm Maya", remembered.

`scripts/lens_reachability.py` reported Name Capture as
**"[no Brain-side constructor]"**: `social_lens/introduction.py` had implemented
the whole thing — a closed grammar of self-introductions, a consent flow, an
offer card and a kept card — and nothing on the shipped product ever built an
`IntroductionCapture`. The ear heard "Hi, I'm Maya" and nothing happened. Both
its cards sat in the HUD checker's undeclared bucket, built and never pushed.

This is the single most-cited reason people say they want glasses like these,
so the thing worth guarding hardest is that it stays CONSENT-FIRST:

  * hearing a name saves nothing — it stages an offer that expires by itself;
  * ordinary chatter produces nothing, because only a closed grammar captures;
  * the Veil closes the ear entirely;
  * `intro_auto_keep` — the only switch that writes without being asked — is
    separately opt-in on top of the feature's own opt-in on top of the mic's.

A feature that remembers names is one bad default away from a feature that
records everyone who talks near you.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server import Brain


def _brain(veiled=False, enabled=True, auto_keep=False):
    b = Brain(pathlib.Path(tempfile.mkdtemp()))
    b.config.intro_capture_enabled = enabled
    b.config.intro_auto_keep = auto_keep
    if veiled:
        b.incognito_now = lambda: True                  # type: ignore[method-assign]
    return b


def _names(b):
    return [p["name"] for p in b.people()]


class TestItHearsAnIntroductionAndOnlyAnIntroduction:
    def test_a_self_introduction_offers(self):
        b = _brain()
        card = b.intro().heard("Hi, I'm Maya")
        assert card and card["type"] == "IntroOfferCard"
        assert card["primary"] == "Maya"

    @pytest.mark.parametrize("said", [
        "we should ship on Friday",
        "I'm running late",                 # soft trigger, not a name
        "I'm sorry about that",
        "the lease is due next week",
        "what did Marcus say about the deposit",
        "",
    ])
    def test_ordinary_talk_captures_nothing(self, said):
        """The boundary is people who CHOSE to give you their name. Anything
        that widens this grammar widens who gets recorded."""
        b = _brain()
        assert b.intro().heard(said) is None
        assert _names(b) == []

    def test_hearing_writes_nothing(self):
        """The whole consent shape in one assertion."""
        b = _brain()
        b.intro().heard("Hi, I'm Maya")
        assert _names(b) == [], "a heard name was written without being confirmed"
        assert b.intro().status()["kept"] == 0


class TestConfirmIsTheOnlyThingThatWrites:
    def test_confirm_writes_the_person(self):
        b = _brain()
        b.intro().heard("my name is Priya")
        out = b.intro().confirm()
        assert out["ok"] is True and out["name"] == "Priya"
        assert _names(b) == ["Priya"]

    def test_dismiss_writes_nothing_and_clears_the_offer(self):
        b = _brain()
        b.intro().heard("Hi, I'm Maya")
        assert b.intro().dismiss() == {"ok": True, "dismissed": True}
        assert _names(b) == []
        assert b.intro().confirm()["ok"] is False

    def test_confirming_nothing_is_not_an_error(self):
        b = _brain()
        assert b.intro().confirm() == {"ok": False, "reason": "nothing offered"}

    def test_an_expired_offer_is_refused_rather_than_written(self):
        """An offer forgets itself after OFFER_TTL_S. A tap landing after that
        must not write a name the wearer stopped looking at twelve seconds ago."""
        from dreamlayer.social_lens.introduction import OFFER_TTL_S
        b = _brain()
        ih = b.intro()
        ih.heard("Hi, I'm Maya")
        cap = ih._cap()
        cap._now = lambda: cap.pending.heard_ts + OFFER_TTL_S + 1
        out = ih.confirm()
        assert out["ok"] is False and "expired" in out["reason"]
        assert _names(b) == []

    def test_confirm_can_seed_the_dossier(self):
        b = _brain()
        b.intro().heard("Hi, I'm Maya")
        assert b.intro().confirm(company="Overpass", role="designer")["ok"] is True
        assert _names(b) == ["Maya"]


class TestTheVeilClosesTheEar:
    def test_a_veiled_introduction_is_neither_kept_nor_offered(self):
        b = _brain(veiled=True)
        assert b.intro().heard("Hi, I'm Maya") is None
        assert _names(b) == []
        assert b.intro().confirm()["ok"] is False

    def test_an_unreadable_posture_fails_closed(self):
        b = _brain()
        b.incognito_now = lambda: (_ for _ in ()).throw(RuntimeError("?"))  # type: ignore[method-assign]
        assert b.intro().heard("Hi, I'm Maya") is None
        assert _names(b) == []

    def test_the_veil_falling_between_offer_and_confirm_still_refuses(self):
        """The write goes through `add_person`, which refuses under the shield on
        its own — so a tap that lands as the veil closes is stopped by the store
        even though the offer was staged while it was open."""
        b = _brain()
        b.intro().heard("Hi, I'm Maya")
        b.incognito_now = lambda: True                  # type: ignore[method-assign]
        b.intro().confirm()
        assert _names(b) == [], "a name landed after the veil came down"


class TestTheSwitches:
    def test_off_by_default(self):
        from dreamlayer.ai_brain.server.store import BrainConfig
        cfg = BrainConfig()
        assert cfg.intro_capture_enabled is False
        assert cfg.intro_auto_keep is False

    def test_disabled_hears_nothing(self):
        b = _brain(enabled=False)
        assert b.intro().heard("Hi, I'm Maya") is None
        assert _names(b) == []

    def test_auto_keep_writes_immediately_and_says_so(self):
        b = _brain(auto_keep=True)
        card = b.intro().heard("Hi, I'm Maya")
        assert card and card["type"] == "IntroKeptCard"
        assert _names(b) == ["Maya"], "auto_keep did not reach the People list"

    def test_auto_keep_is_read_fresh_not_frozen_at_construction(self):
        """Turning it off mid-conversation must take effect on the next thing
        said, not at the next restart."""
        b = _brain(auto_keep=True)
        assert b.intro().heard("Hi, I'm Maya")["type"] == "IntroKeptCard"
        b.config.intro_auto_keep = False
        assert b.intro().heard("Hi, I'm Priya")["type"] == "IntroOfferCard"
        assert _names(b) == ["Maya"], "the second name was kept without asking"


class TestTheCardsReachASurface:
    def test_the_offer_is_pushed_veil_ok_false(self):
        """This card is nothing but a name someone said, so it must never ride a
        veil-exempt push."""
        b = _brain()
        seen = []
        b.push_event = lambda kind, card=None, veil_ok=False: (   # type: ignore[method-assign]
            seen.append((kind, card, veil_ok)) or 1)
        b.intro().heard("Hi, I'm Maya")
        assert seen and seen[0][0] == "intro"
        assert seen[0][1]["type"] == "IntroOfferCard" and seen[0][2] is False

    def test_the_kept_card_is_pushed_on_confirm(self):
        b = _brain()
        seen = []
        b.push_event = lambda kind, card=None, veil_ok=False: (   # type: ignore[method-assign]
            seen.append(card) or 1)
        b.intro().heard("Hi, I'm Maya")
        b.intro().confirm()
        assert [c["type"] for c in seen] == ["IntroOfferCard", "IntroKeptCard"]

    def test_the_live_lens_draws_both(self):
        src = pathlib.Path(
            __file__).resolve().parents[1] / "ai_brain" / "server" / "live.py"
        text = src.read_text(encoding="utf-8")
        assert ('else if (t === "IntroOfferCard" || t === "IntroKeptCard") '
                'glassIntroCard(c);') in text
        assert "function glassIntroCard(c){" in text

    def test_the_keep_is_a_real_button_not_painted_text(self):
        """The glass is a canvas with no hit-testing. Painting "KEEP / SKIP" on
        it would be an affordance that does nothing, which is worse than not
        offering one — so the answers ride `notice()`, the mechanism this page
        already uses to take a decision."""
        src = pathlib.Path(
            __file__).resolve().parents[1] / "ai_brain" / "server" / "live.py"
        body = src.read_text(encoding="utf-8").split("function introAsk(", 1)[1]
        head = body.split("\nfunction ", 1)[0]
        assert 'notice(' in head and 'label: "Keep"' in head and 'label: "Skip"' in head
        assert '"/dreamlayer/intro"' in head and '"POST"' in head

    def test_the_device_draws_both(self):
        root = pathlib.Path(__file__).resolve().parents[4]
        lua = root / "halo-lua" / "display" / "renderer.lua"
        if not lua.exists():
            pytest.skip("halo-lua not in this checkout")
        text = lua.read_text(encoding="utf-8")
        assert "IntroOfferCard        = function" in text
        assert "IntroKeptCard         = function" in text
        assert "local function draw_introduction" in text

    def test_the_device_countdown_uses_the_cards_own_ttl(self):
        """The ring and the card's actual expiry must not drift apart — the
        drawing reads `dismiss_ms`, which the builder sets from OFFER_TTL_S."""
        root = pathlib.Path(__file__).resolve().parents[4]
        lua = root / "halo-lua" / "display" / "renderer.lua"
        if not lua.exists():
            pytest.skip("halo-lua not in this checkout")
        body = lua.read_text(encoding="utf-8").split("draw_introduction", 1)[1]
        assert "card.dismiss_ms" in body.split("\nlocal function", 1)[0]

    def test_the_offer_ttl_matches_between_the_module_and_the_device(self):
        from dreamlayer.social_lens.introduction import OFFER_TTL_S
        root = pathlib.Path(__file__).resolve().parents[4]
        anim = root / "halo-lua" / "display" / "animations.lua"
        if not anim.exists():
            pytest.skip("halo-lua not in this checkout")
        import re
        m = re.search(r"IntroOfferCard\s*=\s*(\d+)", anim.read_text(encoding="utf-8"))
        assert m and int(m.group(1)) == int(OFFER_TTL_S * 1000)


class TestTheEarDrivesIt:
    def test_ingest_caption_offers_a_heard_name(self):
        from dreamlayer.ai_brain.server.ear import EarHost
        b = _brain()
        EarHost(b).ingest_caption("Hi, I'm Maya")
        assert b.intro().status()["pending"] is True
        assert _names(b) == [], "the ear wrote a name without a confirm"

    def test_the_ear_is_fed_after_the_pii_scrub(self):
        src = pathlib.Path(
            __file__).resolve().parents[1] / "ai_brain" / "server" / "ear.py"
        body = src.read_text(encoding="utf-8").split("def ingest_caption(", 1)[1]
        assert body.index("default_redactor") < body.index("self.brain.intro()")


class TestStatusSaysCountsNotNames:
    def test_status_never_carries_the_pending_name(self):
        """The name on a live offer is already on the wearer's own glass;
        echoing it to their paired phone tells them nothing they are not looking
        at, and puts a captured name on one more surface."""
        b = _brain()
        b.intro().heard("Hi, I'm Maya")
        st = b.intro().status()
        assert st["pending"] is True
        assert "Maya" not in str(st)

    def test_counts_track_what_happened(self):
        b = _brain()
        b.intro().heard("Hi, I'm Maya")
        assert b.intro().status()["offered"] == 1
        assert b.intro().status()["kept"] == 0
        b.intro().confirm()
        assert b.intro().status()["kept"] == 1


class TestTheHostSurvivesEverything:
    def test_a_push_failure_does_not_lose_the_offer(self):
        b = _brain()
        b.push_event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no bus"))  # type: ignore[method-assign]
        b.intro().heard("Hi, I'm Maya")
        assert b.intro().status()["pending"] is True
        assert b.intro().confirm()["ok"] is True

    def test_the_capture_is_cached_so_the_offer_survives(self):
        """A fresh `IntroductionCapture` per utterance would drop every offer the
        moment it was made — the pending offer lives on the instance."""
        b = _brain()
        assert b.intro() is b.intro()
        b.intro().heard("Hi, I'm Maya")
        assert b.intro()._cap().pending is not None
