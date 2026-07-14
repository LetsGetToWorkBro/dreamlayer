"""EmberStore — keeps are idempotent, prompts are place-gated, the burn
blanks the answer, and the file survives independently of the memory DB."""

from dreamlayer.ember import EmberStore, RecallOutcome
from dreamlayer.ember.engram import TendingCandidate

NOW = 1_700_000_000.0
DAY = 86400.0


def store_with_one(sig=""):
    st = EmberStore()
    e = st.keep("k1", "What did Maya say?",
                "Maya said her first full sentence in Spanish",
                NOW, place_signature=sig)
    return st, e


class TestKeep:
    def test_keep_is_idempotent_on_moment_key(self):
        st, e = store_with_one()
        again = st.keep("k1", "different cue", "different answer", NOW + DAY)
        assert again.id == e.id
        assert again.cue == e.cue, "a double-tap must not reset a curve"
        assert len(st.engrams()) == 1

    def test_round_trip_preserves_the_state(self):
        st, e = store_with_one(sig="sig-kitchen")
        back = st.get(e.id)
        assert back == e
        assert back.place_signature == "sig-kitchen"


class TestDue:
    def test_not_due_before_the_curve_says_so(self):
        st, e = store_with_one()
        assert st.due(NOW) == []
        assert [d.id for d in st.due(e.state.due_ts)] == [e.id]

    def test_place_anchored_engram_fires_only_at_its_place(self):
        st, e = store_with_one(sig="sig-kitchen")
        due_ts = e.state.due_ts
        assert st.due(due_ts) == []                      # nowhere: silent
        assert st.due(due_ts, "sig-office") == []        # wrong doorway
        assert len(st.due(due_ts, "sig-kitchen")) == 1   # the method of loci

    def test_unanchored_engram_fires_anywhere(self):
        st, e = store_with_one(sig="")
        assert len(st.due(e.state.due_ts, "sig-anywhere")) == 1
        assert len(st.due(e.state.due_ts)) == 1

    def test_most_overdue_first_and_limit(self):
        st = EmberStore()
        a = st.keep("a", "cue a", "ans a", NOW - 40 * DAY)
        b = st.keep("b", "cue b", "ans b", NOW)
        due = st.due(NOW + 400 * DAY, limit=2)
        assert [d.id for d in due] == [a.id, b.id]
        assert len(st.due(NOW + 400 * DAY, limit=1)) == 1


class TestReview:
    def test_review_advances_and_persists(self):
        st, e = store_with_one()
        upd = st.record_review(e.id, RecallOutcome.GOOD, e.state.due_ts)
        assert upd.state.reps == e.state.reps + 1
        assert st.get(e.id).state == upd.state

    def test_burned_engrams_never_review_never_fire(self):
        st, e = store_with_one()
        st.mark_burned(e.id, NOW)
        assert st.record_review(e.id, RecallOutcome.GOOD, NOW + 400 * DAY) is None
        assert st.due(NOW + 400 * DAY) == []


class TestBurn:
    def test_burn_blanks_the_answer(self):
        st, e = store_with_one()
        burned = st.mark_burned(e.id, NOW + DAY)
        assert burned.burned and burned.burned_at == NOW + DAY
        assert burned.answer == "", "after a burn only the cue may remain"
        assert burned.cue == e.cue

    def test_status_counts_the_whole_practice(self):
        st, e = store_with_one()
        st.keep("k2", "cue2", "ans2", NOW)
        st.mark_burned(e.id, NOW)
        s = st.status(NOW + 400 * DAY)
        assert s["tended"] == 1 and s["burned"] == 1 and s["due"] == 1


class TestTending:
    def cand(self, i, salience=1.0):
        return TendingCandidate(id=0, kind="memory", summary=f"moment {i}",
                                cue=f"cue {i}", salience=salience)

    def test_candidates_ranked_by_salience(self):
        st = EmberStore()
        st.add_candidates([self.cand(1, 0.5), self.cand(2, 0.9)], NOW)
        assert [c.cue for c in st.candidates()] == ["cue 2", "cue 1"]

    def test_an_offer_is_for_one_morning(self):
        # unresolved offers from an earlier night are released, not queued
        st = EmberStore()
        st.add_candidates([self.cand(1)], NOW)
        st.add_candidates([self.cand(2)], NOW + DAY)
        cues = [c.cue for c in st.candidates()]
        assert cues == ["cue 2"], "a ritual must never become an inbox"

    def test_resolve_is_single_shot(self):
        st = EmberStore()
        st.add_candidates([self.cand(1)], NOW)
        cid = st.candidates()[0].id
        assert st.resolve_candidate(cid, kept=True) is not None
        assert st.resolve_candidate(cid, kept=True) is None
        assert st.candidates() == []


class TestPersistence:
    def test_survives_reopen(self, tmp_path):
        p = str(tmp_path / "dreamlayer.db.ember")
        st = EmberStore(p)
        e = st.keep("k1", "cue", "answer", NOW)
        st.record_review(e.id, RecallOutcome.GOOD, e.state.due_ts)
        reopened = EmberStore(p)
        back = reopened.get(e.id)
        assert back.state.reps == 2 and back.cue == "cue"
