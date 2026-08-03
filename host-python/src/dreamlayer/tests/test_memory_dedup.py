"""Near-duplicate collapsing — `memory_dedup`, delivered without the cloud.

The catalogued dependency is `mem0`, whose `Memory()` routes extraction and
embedding through a cloud LLM by default; this repo's own audit calls the
package "cloud-routing". Sending the wearer's memories to a third party in order
to notice that two of them are similar is not a trade a private memory layer can
make, so the collapsing is in-house and dependency-free, and it is what runs.

The load-bearing design fact, which these tests pin from both sides: dedup is a
READ-time pass. `object_lens/providers.MemoryProvider.build` derives "seen
before 5× · last at the kitchen" from `len()` over raw ring entries, so merging
at write time would turn every count into 1 and that row would start lying about
the wearer's own history. At read time the count keeps reading the raw ring and
the list they scrub through stops repeating itself.
"""
from __future__ import annotations

import pytest

from dreamlayer.memory.dedup import (
    NEAR_THRESHOLD, collapse, decayed, similarity, tokens,
)


class TestSimilarity:
    def test_a_restatement_is_near(self):
        assert similarity("I need to call the dentist",
                          "gotta call the dentist") >= NEAR_THRESHOLD

    def test_two_different_commitments_are_not(self):
        # The direction that matters most. Same person, different promise —
        # collapsing these loses one of the wearer's commitments outright.
        assert similarity("send Marcus the lease",
                          "send Marcus the invoice") < NEAR_THRESHOLD

    def test_word_order_does_not_matter(self):
        assert similarity("lease for Marcus", "Marcus lease") == 1.0

    def test_punctuation_and_case_do_not_matter(self):
        assert similarity("Call the DENTIST!", "call the dentist") == 1.0

    def test_two_empty_entries_are_not_the_same_thing(self):
        # 1.0 here would collapse every contentless entry into one.
        assert similarity("", "") == 0.0
        assert similarity("the a of", "to and it") == 0.0

    def test_stopwords_do_not_manufacture_a_match(self):
        assert similarity("I will be at the shop", "I will be at the park") \
            < NEAR_THRESHOLD

    def test_tokens_drop_stopwords_and_single_characters(self):
        assert tokens("I'll be at the shop") == frozenset({"shop"})


class TestCollapse:
    def _rows(self, *texts):
        return [{"t": t} for t in texts]

    def test_near_duplicates_merge_and_count(self):
        got = collapse(self._rows("call the dentist", "gotta call the dentist",
                                  "buy milk"), lambda r: r["t"])
        assert [r["t"] for r, _ in got] == ["call the dentist", "buy milk"]
        assert [n for _, n in got] == [2, 1]

    def test_a_unique_entry_reports_one_not_zero(self):
        got = collapse(self._rows("buy milk"), lambda r: r["t"])
        assert got == [({"t": "buy milk"}, 1)]

    def test_the_first_row_is_the_one_kept(self):
        # Callers hand rows newest-first, so the kept phrasing is the most
        # recent one — the wording the wearer will recognise.
        got = collapse(self._rows("ring the dentist today",
                                  "ring the dentist"), lambda r: r["t"])
        assert got[0][0]["t"] == "ring the dentist today"

    def test_order_is_otherwise_preserved(self):
        got = collapse(self._rows("alpha thing", "beta thing", "gamma thing"),
                       lambda r: r["t"])
        assert [r["t"] for r, _ in got] == ["alpha thing", "beta thing",
                                            "gamma thing"]

    def test_empty_rows_never_merge_with_each_other(self):
        got = collapse(self._rows("", "", "real memory"), lambda r: r["t"])
        assert len(got) == 3

    def test_a_text_accessor_that_raises_does_not_lose_the_row(self):
        def boom(r):
            raise RuntimeError("bad row")
        assert len(collapse(self._rows("a", "b"), boom)) == 2

    def test_nothing_in_nothing_out(self):
        assert collapse([], lambda r: r) == []
        assert collapse(None, lambda r: r) == []

    def test_the_threshold_is_honoured(self):
        rows = self._rows("call the dentist", "call the doctor")
        assert len(collapse(rows, lambda r: r["t"], threshold=0.01)) == 1
        assert len(collapse(rows, lambda r: r["t"], threshold=0.99)) == 2


class TestDecay:
    def test_recent_outweighs_old(self):
        now = 1_000_000.0
        rows = [{"ts": now}, {"ts": now - 7 * 86400.0}]
        got = decayed(rows, lambda r: r["ts"], now)
        assert got[0][1] == pytest.approx(1.0)
        assert got[1][1] == pytest.approx(0.5)

    def test_nothing_ever_reaches_zero(self):
        now = 1_000_000.0
        got = decayed([{"ts": now - 3650 * 86400.0}], lambda r: r["ts"], now)
        assert got[0][1] > 0.0, (
            "an old-but-real memory must stay reachable when nothing newer "
            "matches — decay is a weight, not a cutoff")

    def test_an_unreadable_timestamp_weighs_the_floor(self):
        got = decayed([{"ts": "sometime"}], lambda r: r["ts"], 1.0, floor=0.15)
        assert got[0][1] == pytest.approx(0.15)

    def test_a_future_timestamp_does_not_exceed_one(self):
        got = decayed([{"ts": 2.0}], lambda r: r["ts"], 1.0)
        assert got[0][1] <= 1.0


class TestTheCountThatMustNotLie:
    """The reason this is a read-time pass, asserted against the real provider."""

    def test_the_object_lens_still_counts_every_sighting(self):
        from dreamlayer.memory.ring_buffer import SemanticRingBuffer
        from dreamlayer.object_lens.providers import MemoryProvider
        from dreamlayer.object_lens.recognizer import ObjectSighting
        from dreamlayer.pipelines.ingest import MemoryEvent

        ring = SemanticRingBuffer(16)
        for i in range(4):
            ring.append(MemoryEvent(kind="object", summary="mug",
                                    confidence=0.9, meta={"object": "mug"}),
                        ts=100.0 + i, source="look")
        rows = MemoryProvider(ring).build(
            ObjectSighting(label="mug", confidence=0.9), now=200.0)
        detail = " ".join(r.detail for r in rows if r.label == "seen before")
        assert "4×" in detail, (
            f"repeat sightings stopped being counted: {detail!r} — dedup must "
            "not touch the ring, only what is shown")


class TestTheScrubberUsesIt:
    def test_the_scrub_list_collapses_and_reports_repeats(self):
        from dreamlayer.ai_brain.server.lens_hosts import BrainLenses
        from dreamlayer.memory.ring_buffer import SemanticRingBuffer
        from dreamlayer.pipelines.ingest import MemoryEvent

        host = BrainLenses.__new__(BrainLenses)
        ring = SemanticRingBuffer(32)
        import time as _t
        base = _t.time() - 600.0
        for off, s in ((0.0, "call the dentist"), (10.0, "gotta call the dentist"),
                       (20.0, "buy milk")):
            ring.append(MemoryEvent(kind="note", summary=s, confidence=0.5),
                        ts=base + off, source="passive")
        import threading
        host._ring = ring
        host._seeded = True
        host._lock = threading.RLock()
        host.privacy = type("_G", (), {"allow_recall": staticmethod(lambda: True),
                                       "allow_capture": staticmethod(lambda: True)})()
        out = BrainLenses.scrub(host, hours=99999.0, push=False)
        # The MOST RECENT phrasing survives: rows arrive newest-first, so the
        # wearer sees the words they said last, not the first time they said it.
        assert [n["summary"] for n in out["nodes"]] == [
            "buy milk", "gotta call the dentist"]
        assert out["nodes"][1]["repeats"] == 2
        assert out["total"] == 2, (
            "total must be the merged length — it bounds the index and draws "
            "the progress dot, so a raw total scrubs past the end of the list")

    def test_the_index_stays_inside_the_merged_list(self):
        from dreamlayer.ai_brain.server.lens_hosts import BrainLenses
        from dreamlayer.memory.ring_buffer import SemanticRingBuffer
        from dreamlayer.pipelines.ingest import MemoryEvent

        host = BrainLenses.__new__(BrainLenses)
        ring = SemanticRingBuffer(32)
        import time as _t
        base = _t.time() - 600.0
        for i in range(5):
            ring.append(MemoryEvent(kind="note", summary="call the dentist",
                                    confidence=0.5), ts=base + i,
                        source="passive")
        import threading
        host._ring = ring
        host._seeded = True
        host._lock = threading.RLock()
        host.privacy = type("_G", (), {"allow_recall": staticmethod(lambda: True),
                                       "allow_capture": staticmethod(lambda: True)})()
        out = BrainLenses.scrub(host, index=4, hours=99999.0, push=False)
        assert out["total"] == 1 and out["index"] == 0
        assert out["nodes"][0]["repeats"] == 5


class TestSingleDigitsAreIdentity:
    """Caught by `test_brain_scrub.py`, not by this file — worth keeping here.

    A `len(w) > 1` filter drops a lone digit as noise, and then "moment 0" and
    "moment 1" have identical token sets. The existing scrub test seeds exactly
    that shape and went from 5 nodes to 1. The same bug in the wild merges "call
    at 5" into "call at 9" and one of the wearer's commitments is simply gone,
    with a perfectly reasonable-looking entry left behind.
    """

    def test_numbered_moments_stay_apart(self):
        assert similarity("moment 0", "moment 1") < NEAR_THRESHOLD
        assert len(collapse([{"t": f"moment {i}"} for i in range(5)],
                            lambda r: r["t"])) == 5

    def test_times_stay_apart(self):
        assert similarity("call Marcus at 5", "call Marcus at 9") \
            < NEAR_THRESHOLD

    def test_a_lone_letter_is_still_noise(self):
        assert tokens("a b c dentist") == frozenset({"dentist"})

    def test_digits_survive_tokenising(self):
        assert "5" in tokens("call at 5")
