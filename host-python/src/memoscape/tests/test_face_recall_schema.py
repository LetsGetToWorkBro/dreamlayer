"""Tests for FaceRecall schema dataclasses."""
import pytest
from memoscape.face_recall.schema import (
    ContactRecord, MatchResult, FaceRecallResult,
)


def make_contact(cid="c001", name="Alex", conf=0.92):
    return ContactRecord(
        contact_id=cid,
        name=name,
        embedding=[0.1] * 512,
        company="Acme Corp",
        role="Engineer",
        last_met="2026-01-12",
        notes="Likes cold brew",
    )


class TestContactRecord:
    def test_valid_creation(self):
        c = make_contact()
        assert c.name == "Alex"
        assert len(c.embedding) == 512

    def test_rejects_wrong_embedding_length(self):
        with pytest.raises(ValueError):
            ContactRecord(contact_id="x", name="X", embedding=[0.1] * 10)

    def test_context_line_all_fields(self):
        c = make_contact()
        line = c.context_line()
        assert "Acme Corp" in line
        assert "Engineer" in line
        assert "2026-01-12" in line

    def test_context_line_empty_when_no_fields(self):
        c = ContactRecord(contact_id="x", name="X", embedding=[0.0] * 512)
        assert c.context_line() == ""

    def test_context_line_partial(self):
        c = ContactRecord(contact_id="x", name="X", embedding=[0.0] * 512,
                          company="Acme")
        assert "Acme" in c.context_line()


class TestFaceRecallResultNoFace:
    def test_no_face_card_type(self):
        r = FaceRecallResult(match=None, frame_confidence=0.0, no_face=True)
        card = r.to_hud_card()
        assert card["type"] == "FaceRecallCard"
        assert "No face" in card["primary"]

    def test_no_face_dismiss_short(self):
        r = FaceRecallResult(match=None, frame_confidence=0.0, no_face=True)
        assert r.to_hud_card()["dismiss_ms"] == 2500


class TestFaceRecallResultNoMatch:
    def test_no_match_card(self):
        r = FaceRecallResult(match=None, frame_confidence=0.8, no_match=True)
        card = r.to_hud_card()
        assert "No match" in card["primary"]

    def test_no_match_grey_color(self):
        r = FaceRecallResult(match=None, frame_confidence=0.8, no_match=True)
        assert r.to_hud_card()["color"] == 0x7BEF


class TestFaceRecallResultMatch:
    def test_match_card_shows_name(self):
        c = make_contact()
        m = MatchResult(contact=c, confidence=0.92, is_match=True)
        r = FaceRecallResult(match=m, frame_confidence=0.9)
        card = r.to_hud_card()
        assert card["primary"] == "Alex"

    def test_high_confidence_green_color(self):
        c = make_contact()
        m = MatchResult(contact=c, confidence=0.92, is_match=True)
        r = FaceRecallResult(match=m, frame_confidence=0.9)
        assert r.to_hud_card()["color"] == 0x07E0

    def test_medium_confidence_yellow(self):
        c = make_contact()
        m = MatchResult(contact=c, confidence=0.75, is_match=True)
        r = FaceRecallResult(match=m, frame_confidence=0.9)
        assert r.to_hud_card()["color"] == 0xFFE0

    def test_low_confidence_orange(self):
        c = make_contact()
        m = MatchResult(contact=c, confidence=0.67, is_match=True)
        r = FaceRecallResult(match=m, frame_confidence=0.9)
        assert r.to_hud_card()["color"] == 0xFD20

    def test_card_has_contact_id(self):
        c = make_contact(cid="xyz")
        m = MatchResult(contact=c, confidence=0.90, is_match=True)
        r = FaceRecallResult(match=m, frame_confidence=0.9)
        assert r.to_hud_card()["contact_id"] == "xyz"

    def test_card_footer_has_percent(self):
        c = make_contact()
        m = MatchResult(contact=c, confidence=0.92, is_match=True)
        r = FaceRecallResult(match=m, frame_confidence=0.9)
        assert "%" in r.to_hud_card()["footer"]

    def test_card_eyebrow(self):
        c = make_contact()
        m = MatchResult(contact=c, confidence=0.92, is_match=True)
        r = FaceRecallResult(match=m, frame_confidence=0.9)
        assert r.to_hud_card()["eyebrow"] == "FACE RECALL"
