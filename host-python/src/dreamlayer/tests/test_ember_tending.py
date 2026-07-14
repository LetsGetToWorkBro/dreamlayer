"""Tending + grading — the night offers (privately, deterministically),
cues point without revealing, and grading is recall-shaped, not exam-shaped."""

from dreamlayer.ember import EmberStore, RecallOutcome, grade_recall, make_cue
from dreamlayer.ember.grading import recall_score
from dreamlayer.ember.tending import MAX_CANDIDATES, TendingPass
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent

NOW = 1_700_000_000.0
H = 3600.0


def ring_with(events, capacity=64):
    ring = SemanticRingBuffer(capacity=capacity)
    for hours_ago, kind, summary, conf, meta in events:
        ring.append(MemoryEvent(kind=kind, summary=summary,
                                confidence=conf, meta=meta or {}),
                    ts=NOW - hours_ago * H)
    return ring


def a_day():
    return ring_with([
        (10, "promise",      "send Marcus the lease by Friday",           0.9, None),
        (7,  "conversation", "Maya said her first full sentence in Spanish", 0.9, None),
        (5,  "memory",       "keys on the kitchen counter",               0.7, None),
        (2,  "memory",       "a grey cat on the windowsill",              0.4, {"private": True}),
        (1,  "memory",       "hm",                                        0.1, None),
    ])


class TestGather:
    def test_deterministic_and_ranked(self):
        p = TendingPass(EmberStore(), now_fn=lambda: NOW)
        a = p.gather(a_day(), now=NOW)
        b = p.gather(a_day(), now=NOW)
        assert [c.summary for c in a] == [c.summary for c in b]
        assert a[0].salience >= a[-1].salience

    def test_private_moments_are_never_offered(self):
        offers = TendingPass(EmberStore()).gather(a_day(), now=NOW)
        assert all("grey cat" not in c.summary for c in offers), \
            "what the veil hid must never appear on a tending card"

    def test_low_salience_days_can_offer_nothing(self):
        ring = ring_with([(1, "memory", "unremarkable", 0.05, None)])
        assert TendingPass(EmberStore()).gather(ring, now=NOW) == []

    def test_capped_at_a_handful(self):
        ring = ring_with([(h, "memory", f"a fine moment number {h}", 0.9, None)
                          for h in range(1, 20)])
        offers = TendingPass(EmberStore()).gather(ring, now=NOW)
        assert len(offers) <= MAX_CANDIDATES

    def test_the_nights_dreams_boost_the_morning_offers(self):
        from dreamlayer.rem.bias import event_key

        class Reel:
            night_seed = 7
            dream_counts = {event_key("memory", "keys on the kitchen counter"): 3}

        p = TendingPass(EmberStore())
        plain = {c.summary: c.salience for c in p.gather(a_day(), now=NOW)}
        dreamed = {c.summary: c.salience
                   for c in p.gather(a_day(), reel=Reel(), now=NOW)}
        assert dreamed["keys on the kitchen counter"] > \
            plain["keys on the kitchen counter"]

    def test_run_stages_into_the_store(self):
        st = EmberStore()
        staged = TendingPass(st, now_fn=lambda: NOW).run(a_day())
        assert staged and st.candidates()
        assert all(c.id > 0 for c in staged)


class TestCues:
    def test_cue_never_contains_the_whole_answer(self):
        for kind, summary in [
            ("conversation", "Maya said her first full sentence in Spanish"),
            ("promise", "send Marcus the lease by Friday"),
            ("person", "met Maya about the contract"),
            ("memory", "keys on the kitchen counter"),
        ]:
            cue = make_cue(kind, summary)
            assert cue and summary.lower() not in cue.lower()

    def test_said_template_names_the_speaker_only(self):
        cue = make_cue("conversation",
                       "Maya said her first full sentence in Spanish")
        assert cue == "What did Maya say?"
        assert "Spanish" not in cue

    def test_empty_summary_still_yields_a_cue(self):
        assert make_cue("memory", "") == "What happened here?"


class TestGrading:
    ANSWER = "Maya said her first full sentence in Spanish"

    def test_retelling_in_your_own_words_scores_well(self):
        got = grade_recall(
            "she said her first full spanish sentence at the table",
            self.ANSWER)
        assert got in (RecallOutcome.GOOD, RecallOutcome.EASY)

    def test_a_fragment_is_hard_not_forgot(self):
        assert grade_recall("something in spanish",
                            self.ANSWER) == RecallOutcome.HARD

    def test_an_honest_miss_is_forgot(self):
        assert grade_recall("no idea at all sorry",
                            self.ANSWER) == RecallOutcome.FORGOT

    def test_verbosity_never_scores_worse_than_parroting(self):
        short = recall_score("first sentence Spanish Maya said full",
                             self.ANSWER)
        long = recall_score(
            "oh that was the evening Maya said her first full sentence "
            "in Spanish, we were making dinner and she just came out with it",
            self.ANSWER)
        assert long >= short

    def test_similarity_hook_only_ever_grades_more_gently(self):
        lex = recall_score("completely different words", self.ANSWER)
        up = recall_score("completely different words", self.ANSWER,
                          similarity_fn=lambda a, b: 0.9)
        down = recall_score("completely different words", self.ANSWER,
                            similarity_fn=lambda a, b: 0.0)
        assert up >= 0.9 and down == lex

    def test_broken_similarity_hook_degrades_silently(self):
        def boom(a, b):
            raise RuntimeError("no brain tonight")
        assert recall_score("in spanish", self.ANSWER, similarity_fn=boom) == \
            recall_score("in spanish", self.ANSWER)
