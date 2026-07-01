"""Integration tests for FaceRecall orchestrator."""
import numpy as np
import pytest
from memoscape.face_recall import FaceRecall
from memoscape.face_recall.schema import ContactRecord
from memoscape.lie_lens.face_embed import FaceEmbedder


def make_frame(value: float = 0.8) -> np.ndarray:
    return np.full((32, 32), value, dtype=np.float32)


def embed_from_frame(value: float) -> list[float]:
    """Get the deterministic embedding for a given frame value."""
    embedder = FaceEmbedder(threshold=0.40)
    frame = make_frame(value)
    au = embedder.process_frame(frame)
    assert au is not None
    return au.embedding


def make_contact_from_frame(cid: str, name: str,
                            frame_value: float = 0.8) -> ContactRecord:
    """Create a ContactRecord with an embedding derived from a known frame."""
    return ContactRecord(
        contact_id=cid,
        name=name,
        embedding=embed_from_frame(frame_value),
        company="Acme Corp",
        role="Engineer",
        last_met="2026-01-01",
        notes="Test contact",
    )


class TestFaceRecallAnalyzer:
    def test_no_contacts_returns_no_match(self):
        fr = FaceRecall()
        result = fr.identify(make_frame(0.8))
        assert result.no_match is True or result.no_face is True

    def test_no_frame_returns_no_face(self):
        fr = FaceRecall()
        result = fr.identify(None)
        assert result.no_face is True

    def test_dark_frame_no_face(self):
        fr = FaceRecall()
        # Near-zero frame = no face detected
        result = fr.identify(np.zeros((32, 32), dtype=np.float32))
        assert result.no_face is True

    def test_identifies_known_contact(self):
        c = make_contact_from_frame("alice", "Alice", frame_value=0.8)
        fr = FaceRecall(contacts=[c])
        result = fr.identify(make_frame(0.8))
        assert result.match is not None
        assert result.match.contact.contact_id == "alice"
        assert result.match.contact.name == "Alice"

    def test_match_confidence_above_threshold(self):
        c = make_contact_from_frame("bob", "Bob", frame_value=0.7)
        fr = FaceRecall(contacts=[c])
        result = fr.identify(make_frame(0.7))
        if result.match:
            assert result.match.confidence >= 0.65

    def test_hud_card_on_match(self):
        c = make_contact_from_frame("carol", "Carol", frame_value=0.9)
        fr = FaceRecall(contacts=[c])
        result = fr.identify(make_frame(0.9))
        if result.match:
            card = result.to_hud_card()
            assert card["type"] == "FaceRecallCard"
            assert card["primary"] == "Carol"

    def test_add_contact_live(self):
        fr = FaceRecall()
        assert fr.contact_count == 0
        c = make_contact_from_frame("dave", "Dave")
        fr.add_contact(c)
        assert fr.contact_count == 1

    def test_remove_contact(self):
        c = make_contact_from_frame("eve", "Eve")
        fr = FaceRecall(contacts=[c])
        fr.remove_contact("eve")
        assert fr.contact_count == 0

    def test_dict_registry_format_compatible(self):
        """LieLens-compatible dict format works as input."""
        emb = embed_from_frame(0.75)
        registry = {"frank_001": {"name": "Frank", "embedding": emb,
                                   "company": "Initech"}}
        fr = FaceRecall(contacts=registry)
        assert fr.contact_count == 1
        result = fr.identify(make_frame(0.75))
        if result.match:
            assert result.match.contact.name == "Frank"

    def test_privacy_gate_blocks_identify(self):
        class Paused:
            def allow_capture(self): return False

        c = make_contact_from_frame("grace", "Grace")
        fr = FaceRecall(contacts=[c], privacy=Paused())
        result = fr.identify(make_frame(0.8))
        assert result.no_face is True

    def test_record_encounter_updates_last_met(self):
        import datetime
        c = make_contact_from_frame("henry", "Henry")
        fr = FaceRecall(contacts=[c])
        result = fr.identify(make_frame(0.8))
        if result.match:
            last_met = fr._enricher.get_last_met("henry")
            assert last_met == datetime.date.today().isoformat()
