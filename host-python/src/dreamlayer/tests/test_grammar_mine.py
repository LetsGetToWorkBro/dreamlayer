"""test_grammar_mine.py — grammar mining (INNOVATION_SESSION 5.3, last sub-part).

A recurring word across fall-through (label) beats is a feature request for the
closed grammar. Pins that only fall-throughs are mined, recognised commands and
stopwords/known vocab are ignored, recurrence is required, counts persist
locally, and the Brain surfaces the roadmap.
"""
from __future__ import annotations

from dreamlayer.reality_compiler.v2 import GrammarMiner, RealityCompilerV2
from dreamlayer.reality_compiler.v2.rehearsal import parse_utterance


class TestMiner:
    def test_only_fall_throughs_are_mined(self):
        m = GrammarMiner()
        m.observe("pulse for ten seconds", ("pulse", 10.0, 2.0))   # a command
        m.observe("done", ("done",))
        assert m.candidates(min_count=1) == []                     # nothing mined

    def test_recurring_unknown_word_surfaces(self):
        m = GrammarMiner()
        for _ in range(3):
            m.observe("vibrate the ring", ("label", "vibrate the ring"))
        cand = m.candidates(min_count=2)
        words = {c["word"] for c in cand}
        assert "vibrate" in words and "ring" in words
        assert "the" not in words                                  # stopword dropped

    def test_known_vocab_is_not_a_candidate(self):
        m = GrammarMiner()
        for _ in range(3):
            m.observe("pulse harder", ("label", "pulse harder"))   # forced fall-through
        words = {c["word"] for c in m.candidates(min_count=2)}
        assert "pulse" not in words and "harder" in words          # 'pulse' is known

    def test_one_off_labels_are_filtered(self):
        m = GrammarMiner()
        m.observe("rolling", ("label", "rolling"))
        m.observe("the sear", ("label", "the sear"))
        assert m.candidates(min_count=2) == []                     # diverse, no signal

    def test_ranked_by_frequency(self):
        m = GrammarMiner()
        for _ in range(5):
            m.observe("buzz twice", ("label", "buzz twice"))
        for _ in range(2):
            m.observe("chime softly", ("label", "chime softly"))
        cand = m.candidates()
        assert cand[0]["word"] == "buzz" and cand[0]["count"] == 5

    def test_persists_and_rehydrates(self, tmp_path):
        path = tmp_path / "grammar.json"
        m = GrammarMiner(path)
        for _ in range(2):
            m.observe("vibrate now", ("label", "vibrate now"))
        # a fresh miner on the same file recovers the counts
        m2 = GrammarMiner(path)
        assert any(c["word"] == "vibrate" for c in m2.candidates(min_count=2))


class TestCompilerAndBrain:
    def test_mine_utterance_parses_and_counts(self, tmp_path):
        rc = RealityCompilerV2(vault_dir=tmp_path / "v")
        for _ in range(3):
            rc.mine_utterance("vibrate the band")     # falls out of the grammar
            rc.mine_utterance("pulse for 5 seconds")  # a real command — ignored
        words = {c["word"] for c in rc.grammar_candidates(min_count=2)}
        assert "vibrate" in words and "band" in words

    def test_brain_surfaces_candidates(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        brain = Brain(tmp_path)
        beats = [{"kind": "say", "text": "vibrate hard"}] * 3
        brain.rc_rehearse("Buzzy", beats)
        cand = brain.rc_grammar_candidates()["candidates"]
        assert any(c["word"] == "vibrate" for c in cand)

    def test_parse_utterance_really_falls_through(self):
        # guard the premise: "vibrate ..." is genuinely unrecognised today
        assert parse_utterance("vibrate the ring")[0] == "label"
