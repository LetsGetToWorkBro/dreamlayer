"""Phase 3 (Batch B + refute fix): hub-side erase + per-person forget actually
scrub every recall-bearing store — asserted on real content, not mocks.

Audit cross-module flag: Retriever.purge_all() had no production caller (the
phone erase wiped the Mac-mini file index but never the orchestrator's own
MemoryDB). A refute pass then proved "erase everything" was still dishonest: it
cleared only the vector DB, leaving the Truth-Lens deception baselines (via a
wrong-method reset() call), the Social Lens, the conversation ledger, and the
on-disk user model. These tests pin that erase_all_memories() and forget_person()
really reach every store — populate genuine content, then assert it is gone.
"""
from __future__ import annotations

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.social_lens.schema import ContactRecord


class FakeBridge:
    def __init__(self):
        self._h = None

    def on_event(self, fn):
        self._h = fn

    def send_raw(self, c):
        pass

    def send_card(self, c, event=None):
        pass

    def send_command(self, c):
        pass

    def inject_event(self, n):
        pass


def _orc():
    return Orchestrator(FakeBridge())


def _emb(seed: float) -> list:
    # a distinct 512-d face vector per person (ContactRecord requires 512-d)
    return [seed] * 512


def _seed_person(orc, cid="maya", name="Maya", seed=0.11):
    orc.social.add_contact(ContactRecord(contact_id=cid, name=name,
                                         embedding=_emb(seed)))
    # a truth deception baseline for this person (reset() would NOT clear this)
    orc.truth._store._backend.set(f"truth_lens_baseline_{cid}", {"calibrated": True})
    orc.conversation.add("the merger closes Friday", speaker=name)


def test_erase_all_reaches_every_recall_store():
    # SECURITY (revert-failing): erase-everything must empty EVERY store that
    # holds recallable content, not just the vector DB.
    orc = _orc()
    orc.db.add_memory("fact", "Maya told me the merger closes Friday", confidence=0.9)
    _seed_person(orc)
    orc.user.name = "Sam"; orc.user._save()
    orc.premonition.observe("coffee", "flat white", ts=1000.0, place="cafe")

    # preconditions
    assert orc.db.memories()
    assert orc.social.contact_count == 1
    assert len(orc.conversation) == 1
    assert orc.truth._store.get_baseline("maya") is not None
    assert orc.user.name == "Sam"
    assert orc.premonition._slots

    out = orc.erase_all_memories()
    assert out["ok"] is True

    # everything is actually gone
    assert orc.db.memories() == []                                 # main store
    assert orc.retriever.search("merger") == []                    # ANN recall
    assert orc.social.contact_count == 0                           # contacts/faces
    assert len(orc.conversation) == 0                              # day-recall
    assert orc.truth._store.get_baseline("maya") is None           # deception baselines
    assert orc.user.name == ""                                     # on-disk user model
    assert orc.premonition._slots == {}                            # recurrence


def test_forget_person_scrubs_social_truth_and_conversation():
    # SECURITY (revert-failing): forgetting a person reaches their contact +
    # dossier (social), deception baseline (truth), AND day-recall (conversation).
    orc = _orc()
    _seed_person(orc, cid="maya", name="Maya", seed=0.11)
    # a second person who must survive
    _seed_person(orc, cid="theo", name="Theo", seed=0.83)

    orc.forget_person("maya")

    assert orc.social.contact_count == 1                          # only Theo left
    assert orc.truth._store.get_baseline("maya") is None          # Maya's baseline gone
    assert orc.truth._store.get_baseline("theo") is not None      # Theo's survives
    # Maya's conversation utterances gone; Theo's remain
    assert orc.conversation.by_speaker("maya") == []
    assert orc.conversation.by_speaker("theo")
