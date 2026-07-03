"""test_perception_wiring.py — the two "connect what already exists" wins.

1) Look at someone → their dossier. SocialLens.identify(frame) matches a face
   against your own contacts; the orchestrator follows the identity card with
   the conversation dossier when the ledger also knows them.
2) A promise you speak becomes a tracked commitment (ledger → extraction → db),
   attributed to whoever you're talking to.
"""
from __future__ import annotations

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.conversation import parse_commitment
from dreamlayer.social_lens.schema import ContactRecord, MatchResult, SocialLensResult
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _cards(br):
    return [f for f in br.raw if f.get("t") == "card"]


class _FakeSocial:
    """Stands in for SocialLens so the wiring is tested without the face model."""
    def __init__(self, name="Marcus Reyes", conf=0.91, match=True):
        self._name, self._conf, self._match = name, conf, match

    def identify(self, frame):
        if not self._match:
            return SocialLensResult(match=None, frame_confidence=0.9, no_match=True)
        contact = ContactRecord(contact_id="c1", name=self._name,
                                embedding=[0.0] * 512, company="Atlas", role="Landlord")
        return SocialLensResult(
            match=MatchResult(contact=contact, confidence=self._conf, is_match=True),
            frame_confidence=0.95)


# -- look at someone → dossier -----------------------------------------------

def test_look_at_person_shows_identity_then_dossier():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.social = _FakeSocial(name="Marcus")
    orc.ingest_caption("send me the signed lease", speaker="Marcus")  # ledger knows him
    out = orc.look_at_person(frame=object())
    assert out and out["person"] == "Marcus"
    kinds = [c["type"] for c in _cards(br)]
    assert "SocialLensCard" in kinds       # identity from your contacts
    assert "PersonDossierCard" in kinds    # + the conversation dossier


def test_look_at_unknown_face_is_silent():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.social = _FakeSocial(match=False)
    assert orc.look_at_person(frame=object()) is None
    assert _cards(br) == []


def test_look_at_contact_without_ledger_history_shows_identity_only():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.social = _FakeSocial(name="Nadia")     # never spoke in the ledger
    out = orc.look_at_person(frame=object())
    assert out["dossier"] is None
    kinds = [c["type"] for c in _cards(br)]
    assert kinds == ["SocialLensCard"]         # identity only, no dossier


# -- a promise you speak → a tracked commitment ------------------------------

def test_parse_commitment_pulls_task_and_due():
    assert parse_commitment("I'll send you the lease by Friday") == {
        "task": "send you the lease by Friday", "due": "by Friday"}
    assert parse_commitment("I will call the plumber tomorrow")["due"] == "tomorrow"
    assert parse_commitment("that sounds great") is None      # not a promise


def test_spoken_promise_becomes_a_commitment_for_the_listener():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.ingest_caption("did you send the lease?", speaker="Marcus")   # who you're with
    orc.ingest_caption("I'll send you the lease by Friday", speaker="")  # you promise
    open_c = orc.db.commitments()
    assert any(c["person"] == "Marcus" and "lease" in c["task"] for c in open_c)
    assert any(c["type"] == "CommitmentRecallCard" for c in _cards(br))


def test_other_peoples_lines_do_not_become_your_commitments():
    orc = Orchestrator(FakeBridge())
    orc.ingest_caption("I'll handle the invoice", speaker="Priya")   # not the wearer
    assert orc.db.commitments() == []


def test_veil_blocks_commitment_capture():
    orc = Orchestrator(FakeBridge())
    orc.privacy.pause()
    orc.ingest_caption("I'll send the report tonight", speaker="")
    assert orc.db.commitments() == []


# -- Contacts sync fans out to the face database -----------------------------

def test_load_contact_faces_enrolls_and_is_recallable():
    orc = Orchestrator(FakeBridge())
    # a contact whose photo the (seam) embedder turns into a 512-d vector
    embed = lambda photo: [0.2] * 512
    n = orc.load_contact_faces(
        [{"name": "Maya", "photo": b"jpeg", "company": "Studio"}], face_embed_fn=embed)
    assert n == 1 and orc.social.contact_count == 1


def test_load_contact_faces_skips_without_a_usable_face():
    orc = Orchestrator(FakeBridge())
    # no photo and no embedding → stays in the People registry only, not the face DB
    assert orc.load_contact_faces([{"name": "No Photo"}]) == 0
    assert orc.social.contact_count == 0
