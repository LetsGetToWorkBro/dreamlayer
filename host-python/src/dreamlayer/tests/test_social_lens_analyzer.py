"""Integration tests for SocialLens orchestrator."""
import numpy as np
from dreamlayer.social_lens import SocialLens
from dreamlayer.social_lens.schema import ContactRecord
from dreamlayer.truth_lens.face_embed import FaceEmbedder


def make_frame(value: float = 0.8) -> np.ndarray:
    return np.full((32, 32), value, dtype=np.float32)


def embed_from_frame(value: float) -> list[float]:
    """Get the deterministic embedding for a given frame value."""
    embedder = FaceEmbedder(threshold=0.40)
    frame = make_frame(value)
    au = embedder.process_frame(frame)
    assert au is not None
    assert au.embedding is not None
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


class TestSocialLensAnalyzer:
    def test_no_contacts_returns_no_match(self):
        fr = SocialLens()
        result = fr.identify(make_frame(0.8))
        assert result.no_match is True or result.no_face is True

    def test_no_frame_returns_no_face(self):
        fr = SocialLens()
        result = fr.identify(None)
        assert result.no_face is True

    def test_dark_frame_no_face(self):
        fr = SocialLens()
        # Near-zero frame = no face detected
        result = fr.identify(np.zeros((32, 32), dtype=np.float32))
        assert result.no_face is True

    def test_identifies_known_contact(self):
        c = make_contact_from_frame("alice", "Alice", frame_value=0.8)
        fr = SocialLens(contacts=[c])
        result = fr.identify(make_frame(0.8))
        assert result.match is not None
        assert result.match.contact.contact_id == "alice"
        assert result.match.contact.name == "Alice"

    def test_match_confidence_above_threshold(self):
        c = make_contact_from_frame("bob", "Bob", frame_value=0.7)
        fr = SocialLens(contacts=[c])
        result = fr.identify(make_frame(0.7))
        if result.match:
            assert result.match.confidence >= 0.65

    def test_hud_card_on_match(self):
        c = make_contact_from_frame("carol", "Carol", frame_value=0.9)
        fr = SocialLens(contacts=[c])
        result = fr.identify(make_frame(0.9))
        if result.match:
            card = result.to_hud_card()
            assert card["type"] == "SocialLensCard"
            assert card["primary"] == "Carol"

    def test_add_contact_live(self):
        fr = SocialLens()
        assert fr.contact_count == 0
        c = make_contact_from_frame("dave", "Dave")
        fr.add_contact(c)
        assert fr.contact_count == 1

    def test_remove_contact(self):
        c = make_contact_from_frame("eve", "Eve")
        fr = SocialLens(contacts=[c])
        fr.remove_contact("eve")
        assert fr.contact_count == 0

    def test_dict_registry_format_compatible(self):
        """TruthLens-compatible dict format works as input."""
        emb = embed_from_frame(0.75)
        registry = {"frank_001": {"name": "Frank", "embedding": emb,
                                   "company": "Initech"}}
        fr = SocialLens(contacts=registry)
        assert fr.contact_count == 1
        result = fr.identify(make_frame(0.75))
        if result.match:
            assert result.match.contact.name == "Frank"

    def test_privacy_gate_blocks_identify(self):
        class Paused:
            def allow_capture(self): return False

        c = make_contact_from_frame("grace", "Grace")
        fr = SocialLens(contacts=[c], privacy=Paused())
        result = fr.identify(make_frame(0.8))
        assert result.no_face is True

    def test_record_encounter_updates_last_met(self):
        import datetime
        c = make_contact_from_frame("henry", "Henry")
        fr = SocialLens(contacts=[c])
        result = fr.identify(make_frame(0.8))
        if result.match:
            last_met = fr._enricher.get_last_met("henry")
            assert last_met == datetime.date.today().isoformat()


class TestForgetAndVeil:
    """Audit 2026-07-14 HIGH: forget purges the whole dossier and write paths
    honor the veil."""

    def test_remove_contact_purges_the_dossier(self):
        c = make_contact_from_frame("ivy", "Ivy")
        fr = SocialLens(contacts=[c])
        fr.add_note_by_id("ivy", "likes climbing")
        fr.add_debt_by_id("ivy", "they_owe", "$20")
        fr._enricher.set_relation("ivy", "colleague")
        assert fr._enricher.get_notes("ivy")
        fr.remove_contact("ivy")
        # nothing about Ivy survives — vector AND dossier are gone
        assert fr._enricher.get_notes("ivy") is None
        assert fr._enricher.get_relation("ivy") is None
        assert fr._enricher.get_debts("ivy") == []
        assert fr._enricher.get_last_met("ivy") is None
        assert fr.contact_count == 0

    def test_write_paths_are_veil_gated(self):
        class Paused:
            def allow_capture(self): return False
        c = make_contact_from_frame("jack", "Jack")
        fr = SocialLens(contacts=[c], privacy=Paused())
        # meeting/annotating a person while veiled writes nothing
        assert fr.meet("Jack", note="hi") is None
        assert fr.add_note("a secret", who="Jack") is None
        assert fr.add_debt("they_owe", "$5", who="Jack") is None
        assert fr.settle(who="Jack") is None
        assert fr._enricher.get_notes("jack") is None
        # re-audit 2026-07-15: the id-resolved twins — the ones the orchestrator
        # actually calls (ops_commitments) — must honor the veil too, not just
        # their name-based siblings.
        assert fr.add_note_by_id("jack", "a secret") is None
        assert fr.add_debt_by_id("jack", "they_owe", "$5") is None
        assert fr.settle_by_id("jack") is None
        assert fr._enricher.get_notes("jack") is None
        assert fr._enricher.get_debts("jack") == []


class TestGrammarNoFalseEnroll:
    def test_call_me_ambiguous_phrases_do_not_enroll(self):
        from dreamlayer.social_lens.introduction import parse_introduction
        assert parse_introduction("call me back later") is None
        assert parse_introduction("call me crazy") is None
        assert parse_introduction("call me maybe") is None
        # a real capitalised name still enrols
        assert parse_introduction("call me Maya") == "Maya"
