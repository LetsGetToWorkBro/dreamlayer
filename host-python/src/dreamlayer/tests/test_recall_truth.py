"""Re-audit wave 5B: the memory spine must return what it stored.

Three verified defects from an adversarial pass:
  * Mem-1: "Nod to Remember" (pin_latest) stored a row with no embedding and
    never indexed it — the flagship save gesture was invisible to ANN recall.
  * Mem-2: a dict conversation wrote each promise TWICE (legacy regex extractor
    + tier-1 pipeline), so one utterance became two reminders.
  * Mem-4 / Int-7: kind-filtered ANN recall starved top_k (kind-blind over-fetch
    filtered afterwards, short-circuiting the exact scan), and `or 0.5` coerced
    a real 0.0 confidence up to 0.5.
"""
from __future__ import annotations

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.retrieval import Retriever, _confidence
from dreamlayer.pipelines.ingest import MemoryEvent


# --- Mem-1: pinned memories are embedded and indexed ------------------------

class _Orc:
    @staticmethod
    def build():
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        return Orchestrator(FakeBridge())


def test_pin_latest_embeds_and_indexes_the_memory():
    orc = _Orc.build()
    orc.ring.append(MemoryEvent(kind="object", summary="red bicycle on the alder rack",
                                confidence=0.6, meta={"object": "bicycle"}), ts=1000.0)
    res = orc.pin_latest()
    assert res["pinned"] is True
    mid = res["memory_id"]
    # the row now carries an embedding (before the fix it was None → invisible
    # to ANN recall and uncounted by the boot drift-rebuild)
    row = orc.db.memory(mid)
    assert row["embedding"] is not None
    # and it is recallable by content
    hits = orc.retriever.search("red bicycle alder rack", top_k=3)
    assert any(m["id"] == mid for _s, m in hits)


# --- Mem-2: one promise, one commitment -------------------------------------

def test_dict_conversation_writes_one_commitment_per_promise():
    orc = _Orc.build()
    conv = {"participants": ["me", "Sarah"],
            "utterances": [{"speaker": "me",
                            "text": "I'll send the report to Sarah by tomorrow"}],
            "summary": "I'll send the report to Sarah by tomorrow"}
    orc.ingest_conversation(conv)
    tasks = [c for c in orc.db.commitments() if "report" in (c["task"] or "").lower()]
    assert len(tasks) == 1, tasks   # was 2 (legacy regex + tier-1 pipeline)


# --- Mem-4 / Int-7: kind filter must not starve, 0.0 conf must not inflate ---

class FakeAnn:
    """A live ANN whose shortlist is FIXED (independent of k) — it models an
    over-fetch that, being kind-blind, happens to surface only a couple of
    matching-kind rows even though more exist in the store."""
    live = True

    def __init__(self, shortlist, size):
        self._shortlist = shortlist  # [(mid, sim)] the ANN would return
        self._size = size

    def __len__(self):
        return self._size

    def search(self, qv, k):
        return self._shortlist[:k]


def test_kind_filter_falls_through_to_exact_when_starved():
    db = MemoryDB(":memory:")
    # five object rows are the answer set; the ANN's similarity shortlist only
    # contains TWO of them (the rest are drowned by high-sim conversations that
    # get kind-filtered out). A kind="object" top_k=3 must still return 3 —
    # falling through to the exhaustive exact scan rather than the starved 2.
    objs = [db.add_memory("object", f"object number {i} on the shelf", confidence=0.8)
            for i in range(5)]
    convs = [db.add_memory("conversation", f"chatter {i}", confidence=0.3)
             for i in range(20)]
    # the ANN shortlist: 14 high-sim conversations + only 2 of the 5 objects
    shortlist = [(c, 0.95 - i * 0.01) for i, c in enumerate(convs[:14])]
    shortlist += [(objs[0], 0.40), (objs[1], 0.39)]
    r = Retriever(db, ann=FakeAnn(shortlist, size=25))
    hits = r.search("show me the objects", kind="object", top_k=3)
    ids = [m["id"] for _s, m in hits]
    assert len(hits) == 3                       # not starved to 2
    assert all(db.memory(i)["kind"] == "object" for i in ids)


# --- Stasis leak: a live bookmark is not a recall answer --------------------

def test_kindless_search_excludes_live_stasis_bookmarks():
    """A live Stasis frame rides a kind="stasis" memories row whose summary is
    the wearer's verbatim unfinished sentence. A kind-less recall ("what did I
    say about…") must NEVER surface it — it is a bookmark, not an answer. The
    exclusion is by construction in Retriever.search, not per-call-site."""
    db = MemoryDB(":memory:")
    answer = db.add_memory("note", "the hinge torque spec is 4 newton metres",
                           confidence=0.9)
    db.add_memory("stasis", "so the hinge torque — wait, where was I",
                  confidence=0.8)
    r = Retriever(db)
    hits = r.search("hinge torque", top_k=5)
    kinds = {m["kind"] for _s, m in hits}
    assert "stasis" not in kinds                 # the held thought stays hidden
    assert any(m["id"] == answer for _s, m in hits)   # the real memory surfaces


def test_kindless_search_excludes_stasis_on_the_ann_path_too():
    db = MemoryDB(":memory:")
    note = db.add_memory("note", "hinge torque spec four nm", confidence=0.9)
    stasis = db.add_memory("stasis", "hinge torque so where was i", confidence=0.8)
    # both sit near the top of the ANN shortlist; the stasis row must still be
    # dropped after retrieval, on the fast path as well as the exact scan
    r = Retriever(db, ann=FakeAnn([(stasis, 0.98), (note, 0.97)], size=2))
    ids = [m["id"] for _s, m in r.search("hinge torque", top_k=5)]
    assert stasis not in ids and note in ids


def test_explicit_stasis_kind_still_returns_them():
    """The exclusion is a default, not a ban: a caller that explicitly asks
    for kind="stasis" (or the composted kind="memory" row) still gets rows."""
    db = MemoryDB(":memory:")
    sid = db.add_memory("stasis", "where was i on the torque", confidence=0.8)
    r = Retriever(db)
    hits = r.search("torque", kind="stasis", top_k=5)
    assert [m["id"] for _s, m in hits] == [sid]
    # and a composted frame (rewritten as kind="memory") is findable normally
    comp = db.add_memory("memory", "the torque thread, folded into memory",
                         confidence=0.6)
    assert any(m["id"] == comp for _s, m in r.search("torque thread", top_k=5))


def test_zero_confidence_is_not_coerced_to_half():
    assert _confidence({"confidence": 0.0}) == 0.0     # known-unsure stays 0.0
    assert _confidence({"confidence": None}) == 0.5    # absent → default
    assert _confidence({}) == 0.5
    # end to end: a confident answer outranks a lexically-identical 0.0 row
    db = MemoryDB(":memory:")
    sure = db.add_memory("note", "the meeting is at noon", confidence=0.9)
    db.add_memory("note", "the meeting is at noon", confidence=0.0)
    r = Retriever(db)
    top = r.search("when is the meeting", top_k=1)
    assert top and top[0][1]["id"] == sure
