"""Tests for Social Lens avatars + PersonContextCard v2 (Halo Cinema v1).

Privacy contract under test: an avatar sprite must NEVER exist for a
non-contact — no-face and no-match results cannot produce a card that
carries one.
"""
from datetime import datetime, timedelta

import pytest

from dreamlayer.social_lens.renderer import (
    AVATAR_SIZE, AvatarCache, build_person_context_card, why_this_person,
)
from dreamlayer.social_lens.schema import ContactRecord, SocialLensResult, MatchResult

pytest.importorskip("PIL")

NOW = datetime(2026, 7, 1, 12, 0, 0)


def make_contact(cid="c-jordan-001", name="Jordan"):
    return ContactRecord(
        contact_id=cid, name=name, embedding=[0.0] * 512,
        company="Studio Atlas", role="Producer", last_met="2026-06-24",
    )


def make_match_result(confidence=0.88):
    return SocialLensResult(
        match=MatchResult(contact=make_contact(), confidence=confidence,
                          is_match=True),
        frame_confidence=0.95,
    )


class FakeRetriever:
    def __init__(self, memories):
        self._memories = memories
    def search(self, query, kind=None, top_k=3):
        return [(m.get("score", 0.5), m) for m in self._memories]


# ---------------------------------------------------------------------------
# AvatarCache
# ---------------------------------------------------------------------------

def test_avatar_is_32x32():
    avatar = AvatarCache().add_contact(make_contact())
    assert avatar.size == (AVATAR_SIZE, AVATAR_SIZE)


def test_avatar_generated_once_and_cached():
    cache = AvatarCache()
    contact = make_contact()
    first = cache.get(contact)
    second = cache.get(contact)
    assert first is second
    assert len(cache) == 1


def test_avatar_is_deterministic_per_contact():
    a = AvatarCache().add_contact(make_contact())
    b = AvatarCache().add_contact(make_contact())
    assert a.tobytes() == b.tobytes()


def test_different_contacts_get_different_avatars():
    cache = AvatarCache()
    a = cache.add_contact(make_contact("c-1", "Ada"))
    b = cache.add_contact(make_contact("c-2", "Bo"))
    assert a.tobytes() != b.tobytes()


# ---------------------------------------------------------------------------
# why_this_person
# ---------------------------------------------------------------------------

def test_why_picks_recent_memory_naming_contact():
    retriever = FakeRetriever([
        {"summary": "Jordan asked about the invoice deadline",
         "ts": (NOW - timedelta(days=3)).isoformat(), "score": 0.9},
    ])
    assert "invoice" in why_this_person(retriever, "Jordan", now=NOW)


def test_why_skips_memories_older_than_30_days():
    retriever = FakeRetriever([
        {"summary": "Jordan mentioned the venue",
         "ts": (NOW - timedelta(days=45)).isoformat(), "score": 0.9},
    ])
    assert why_this_person(retriever, "Jordan", now=NOW) == ""


def test_why_skips_memories_not_naming_contact():
    retriever = FakeRetriever([
        {"summary": "Bought oat milk",
         "ts": (NOW - timedelta(days=1)).isoformat(), "score": 0.9},
    ])
    assert why_this_person(retriever, "Jordan", now=NOW) == ""


def test_why_empty_without_retriever():
    assert why_this_person(None, "Jordan") == ""


# ---------------------------------------------------------------------------
# build_person_context_card — the privacy gate
# ---------------------------------------------------------------------------

def test_card_carries_why_avatar_and_confidence():
    retriever = FakeRetriever([
        {"summary": "Jordan asked about the invoice deadline",
         "ts": (NOW - timedelta(days=3)).isoformat(), "score": 0.9},
    ])
    card = build_person_context_card(
        make_match_result(), retriever=retriever,
        avatar_cache=AvatarCache(), now=NOW,
    )
    assert card["type"] == "PersonContextCard"
    assert card["primary"] == "Jordan"
    assert "invoice" in card["why"]
    assert card["has_avatar"] is True
    assert card["confidence"] == 0.88


def test_no_face_never_produces_card():
    result = SocialLensResult(match=None, frame_confidence=0.2, no_face=True)
    assert build_person_context_card(result, avatar_cache=AvatarCache()) is None


def test_no_match_never_produces_card():
    """A stranger's face must never reach the avatar path."""
    result = SocialLensResult(match=None, frame_confidence=0.9, no_match=True)
    assert build_person_context_card(result, avatar_cache=AvatarCache()) is None


def test_below_threshold_match_never_produces_card():
    result = SocialLensResult(
        match=MatchResult(contact=make_contact(), confidence=0.3,
                          is_match=False),
        frame_confidence=0.9,
    )
    assert build_person_context_card(result, avatar_cache=AvatarCache()) is None


def test_card_without_avatar_cache_has_no_avatar_flag():
    card = build_person_context_card(make_match_result(), avatar_cache=None)
    assert card["has_avatar"] is False


def test_avatar_cache_untouched_by_non_contacts():
    cache = AvatarCache()
    build_person_context_card(
        SocialLensResult(match=None, frame_confidence=0.9, no_match=True),
        avatar_cache=cache,
    )
    assert len(cache) == 0
