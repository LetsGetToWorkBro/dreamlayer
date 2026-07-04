"""Name-you-were-told capture: spoken, in-place, veiled — kept automatically.

Covers the offline grammar, the automatic keep (the default), the older
consent flow behind auto_keep=False, the veil, offer expiry, the name-only
vs face-bearing split, and the round-trip where a kept introduction is
recalled by face on the next identify()."""
import numpy as np
import pytest

from dreamlayer.social_lens import (
    SocialLens, IntroductionCapture, parse_introduction,
)
from dreamlayer.social_lens.introduction import OFFER_TTL_S
from dreamlayer.social_lens.index import ContactIndex
from dreamlayer.social_lens.enricher import ContactEnricher


def make_frame(value: float = 0.8) -> np.ndarray:
    return np.full((32, 32), value, dtype=np.float32)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Paused:
    def allow_capture(self):
        return False


# --------------------------------------------------------------------------
# The grammar: hears only real self-introductions.
# --------------------------------------------------------------------------

class TestParseIntroduction:
    @pytest.mark.parametrize("utterance,expected", [
        ("Hi, I'm Maya", "Maya"),
        ("my name is Maya", "Maya"),
        ("my name's Sam", "Sam"),
        ("call me Deshawn", "Deshawn"),
        ("I am Priya", "Priya"),
        ("this is Marcus", "Marcus"),
        ("hey there, I'm Maya Chen, nice to meet you", "Maya Chen"),
        ("my name is maria del carmen", "Maria Del Carmen"),
    ])
    def test_recognises_names(self, utterance, expected):
        assert parse_introduction(utterance) == expected

    @pytest.mark.parametrize("utterance", [
        "nice to meet you",
        "I'm sorry",
        "I'm running late",
        "so how was your weekend",
        "the meeting is at three",
        "",
        None,
    ])
    def test_refuses_non_introductions(self, utterance):
        assert parse_introduction(utterance) is None

    def test_stops_at_the_first_ordinary_word(self):
        assert parse_introduction("I'm Maya and I work here") == "Maya"

    def test_caps_name_length(self):
        long = "my name is Ana Bella Cara Dora Elle"
        assert len(parse_introduction(long).split()) <= 3


# --------------------------------------------------------------------------
# The default: a self-introduction is kept automatically.
# --------------------------------------------------------------------------

class TestAutomaticKeep:
    def test_heard_keeps_immediately(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx, enricher=ContactEnricher())
        card = cap.heard("I'm Maya", frame=make_frame(0.8))
        assert card["type"] == "IntroKeptCard"
        assert card["primary"] == "Maya"
        assert idx.size == 1                     # saved, no gesture
        assert cap.pending is None               # nothing staged

    def test_kept_card_states_the_fact(self):
        cap = IntroductionCapture(index=ContactIndex())
        card = cap.heard("my name is Sam", frame=make_frame())
        assert card["eyebrow"] == "KEPT"
        assert "double-tap" not in card["detail"]

    def test_ambient_chatter_keeps_nothing(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx)
        assert cap.heard("what a nice day", frame=make_frame()) is None
        assert idx.size == 0

    def test_veil_still_closes_the_ear(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx, privacy=Paused())
        assert cap.heard("I'm Maya", frame=make_frame()) is None
        assert idx.size == 0

    def test_name_only_auto_keep_stays_out_of_the_face_index(self):
        idx = ContactIndex()
        enr = ContactEnricher()
        cap = IntroductionCapture(index=idx, enricher=enr)
        card = cap.heard("I'm Maya")             # no frame -> no face
        assert card["type"] == "IntroKeptCard"
        assert card["has_face"] is False
        assert idx.size == 0                      # never a false-matchable face
        assert enr.get_notes(card["contact_id"])  # kept as a note instead

    def test_confirm_is_a_noop_after_auto_keep(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx)
        cap.heard("I'm Maya", frame=make_frame())
        assert cap.confirm() is None             # already kept in heard()
        assert idx.size == 1


# --------------------------------------------------------------------------
# The consent flow (auto_keep=False): hearing stages, it does not save.
# --------------------------------------------------------------------------

class TestOfferIsVoluntary:
    def test_heard_returns_offer_but_saves_nothing(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx, enricher=ContactEnricher(),
                                  auto_keep=False)
        card = cap.heard("I'm Maya", frame=make_frame())
        assert card["type"] == "IntroOfferCard"
        assert card["primary"] == "Maya"
        assert idx.size == 0                     # nothing stored yet
        assert cap.pending is not None

    def test_ambient_chatter_makes_no_offer(self):
        cap = IntroductionCapture()
        assert cap.heard("what a nice day", frame=make_frame()) is None
        assert cap.pending is None

    def test_confirm_saves_a_recallable_contact(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx, enricher=ContactEnricher(),
                                  auto_keep=False)
        cap.heard("I'm Maya", frame=make_frame(0.8))
        rec = cap.confirm()
        assert rec is not None and rec.name == "Maya"
        assert idx.size == 1
        assert cap.pending is None               # offer consumed

    def test_confirm_without_offer_saves_nothing(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx, auto_keep=False)
        assert cap.confirm() is None
        assert idx.size == 0

    def test_dismiss_drops_the_offer(self):
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx, auto_keep=False)
        cap.heard("I'm Maya", frame=make_frame())
        cap.dismiss()
        assert cap.pending is None
        assert cap.confirm() is None
        assert idx.size == 0


# --------------------------------------------------------------------------
# The veil, expiry, and the name-only path.
# --------------------------------------------------------------------------

class TestPrivacyAndLifecycle:
    def test_veil_closes_the_ear(self):
        cap = IntroductionCapture(privacy=Paused())
        assert cap.heard("I'm Maya", frame=make_frame()) is None
        assert cap.pending is None

    def test_offer_expires_unconfirmed(self):
        clock = Clock()
        idx = ContactIndex()
        cap = IntroductionCapture(index=idx, now_fn=clock, auto_keep=False)
        cap.heard("I'm Maya", frame=make_frame())
        clock.t += OFFER_TTL_S + 1.0
        cap.tick()
        assert cap.pending is None
        assert cap.confirm() is None

    def test_name_only_offer_stays_out_of_the_face_index(self):
        idx = ContactIndex()
        enr = ContactEnricher()
        cap = IntroductionCapture(index=idx, enricher=enr, auto_keep=False)
        card = cap.heard("I'm Maya")             # no frame -> no face
        assert card["has_face"] is False
        rec = cap.confirm()
        assert rec is not None and rec.name == "Maya"
        assert idx.size == 0                      # never a false-matchable face
        assert enr.get_notes(rec.contact_id)      # kept as a note instead


# --------------------------------------------------------------------------
# End to end through SocialLens: told a name, then recalled by face.
# --------------------------------------------------------------------------

class TestSocialLensRoundTrip:
    def test_introduce_then_recall_by_face(self):
        fr = SocialLens()
        frame = make_frame(0.83)
        card = fr.offer_introduction("hi, my name is Maya", frame=frame)
        assert card and card["primary"] == "Maya"
        assert card["type"] == "IntroKeptCard"   # kept automatically
        assert fr.contact_count == 1

        # the same face now recalls the name you were given
        result = fr.identify(make_frame(0.83))
        assert result.match is not None
        assert result.match.contact.name == "Maya"

    def test_consent_flow_round_trip(self):
        fr = SocialLens(auto_keep_introductions=False)
        frame = make_frame(0.83)
        card = fr.offer_introduction("hi, my name is Maya", frame=frame)
        assert card and card["type"] == "IntroOfferCard"
        assert fr.contact_count == 0             # still just an offer

        saved = fr.confirm_introduction(company="Acme")
        assert saved is not None
        assert fr.contact_count == 1

        result = fr.identify(make_frame(0.83))
        assert result.match is not None
        assert result.match.contact.name == "Maya"

    def test_veil_blocks_capture_through_social_lens(self):
        fr = SocialLens(privacy=Paused())
        assert fr.offer_introduction("I'm Maya", frame=make_frame()) is None
        assert fr.contact_count == 0
