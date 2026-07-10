"""test_repertoire_ranker.py — the compiler teaches itself (INNOVATION 5.3).

The repertoire ranker scores each kept figment by use frequency, completion
rate (finished vs. banished), and time-of-day fit, and offers the right machine
at the right hour. Pins the learner, its persistence through the vault, and the
Brain surfacing a ranked list + a suggestion.
"""
from __future__ import annotations

from dreamlayer.reality_compiler.v2 import (
    RepertoireRanker, RealityCompilerV2, Figment, Scene, TextLine, Transition, END,
)


def _fig(name, initial="a"):
    f = Figment(name=name, initial=initial)
    f.add_scene(Scene(id="a", duration_sec=5.0, lines=[TextLine(name, row=0)],
                      on_timeout=[Transition(target=END)]))
    return f


# -- the learner --------------------------------------------------------------

class TestRanker:
    def test_completion_beats_banishment(self):
        r = RepertoireRanker()
        for _ in range(4):
            r.observe("keep", "deploy", hour=8); r.observe("keep", "complete")
            r.observe("drop", "deploy", hour=8); r.observe("drop", "banish")
        assert r.score("keep", 8) > r.score("drop", 8)

    def test_time_of_day_fit(self):
        r = RepertoireRanker()
        for _ in range(5):
            r.observe("morning", "deploy", hour=7)
            r.observe("evening", "deploy", hour=20)
        # at 7am the morning machine fits better; at 8pm the evening one
        assert r.score("morning", 7) > r.score("evening", 7)
        assert r.score("evening", 20) > r.score("morning", 20)

    def test_frequency_rewards_use(self):
        r = RepertoireRanker()
        for _ in range(10):
            r.observe("often", "deploy", hour=12)
        r.observe("rare", "deploy", hour=12)
        assert r.score("often", 12) > r.score("rare", 12)

    def test_unknown_figment_is_neutral(self):
        r = RepertoireRanker()
        # 0.5 completion, 0.5 time-fit, 0 freq → weighted neutral-ish, bounded
        assert 0.0 <= r.score("never-seen", 12) <= 1.0

    def test_rank_orders_best_first(self):
        r = RepertoireRanker()
        for _ in range(4):
            r.observe("x", "deploy", hour=9); r.observe("x", "complete")
        entries = [{"id": "y", "name": "Y"}, {"id": "x", "name": "X"}]
        assert [e["id"] for e in r.rank(entries, 9)][0] == "x"

    def test_suggest_needs_confidence_and_history(self):
        r = RepertoireRanker()
        # one lightly-used figment is not offered
        r.observe("z", "deploy", hour=9)
        assert r.suggest([{"id": "z", "name": "Z"}], 9) is None
        # a well-used, well-finished one, at its hour, is
        for _ in range(5):
            r.observe("z", "deploy", hour=9); r.observe("z", "complete")
        s = r.suggest([{"id": "z", "name": "Z"}], 9)
        assert s and s["id"] == "z" and "start the usual" in s["say"].lower()

    def test_suggest_skips_the_usually_banished(self):
        r = RepertoireRanker()
        for _ in range(6):
            r.observe("bad", "deploy", hour=9); r.observe("bad", "banish")
        assert r.suggest([{"id": "bad", "name": "Bad"}], 9) is None


# -- persistence through the vault + RealityCompilerV2 ------------------------

class TestRealityCompilerWiring:
    def test_deploy_logs_the_hour_and_feeds_the_ranker(self, tmp_path):
        rc = RealityCompilerV2(vault_dir=tmp_path / "v",
                               now_fn=lambda: 1_700_000_000.0)  # fixed clock
        fig = _fig("Timer"); rc.keep(fig)
        rc.deploy(fig.id)
        hist = rc.vault.performance_history(fig.id)
        assert hist and hist[-1]["action"] == "deploy" and "hour" in hist[-1]
        assert rc.ranker._stat(fig.id).deploys == 1

    def test_ranker_rehydrates_from_the_vault(self, tmp_path):
        vault_dir = tmp_path / "v"
        rc = RealityCompilerV2(vault_dir=vault_dir, now_fn=lambda: 1_700_000_000.0)
        fig = _fig("Circuit"); rc.keep(fig)
        for _ in range(3):
            rc.deploy(fig.id); rc.record_outcome(fig.id, "complete")
        # a fresh compiler on the same vault recovers the learned stats
        rc2 = RealityCompilerV2(vault_dir=vault_dir)
        st = rc2.ranker._stat(fig.id)
        assert st.deploys == 3 and st.completion > 0.5

    def test_suggest_after_a_routine_forms(self, tmp_path):
        rc = RealityCompilerV2(vault_dir=tmp_path / "v",
                               now_fn=lambda: 1_700_000_000.0)
        fig = _fig("Morning"); rc.keep(fig)
        for _ in range(5):
            rc.deploy(fig.id); rc.record_outcome(fig.id, "complete")
        hour = rc._hour()
        s = rc.suggest(hour)
        assert s and s["id"] == fig.id


# -- the Brain surfaces it ----------------------------------------------------

class TestBrainSurface:
    def _brain(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        return Brain(tmp_path)

    def test_repertoire_is_ranked_and_carries_a_suggestion(self, tmp_path):
        brain = self._brain(tmp_path)
        # build a used routine via the native path (deploys a figment)
        out = brain.rc_native("timer", {"seconds": 30, "label": "T"})
        fid = out["figment_id"]
        brain.rc_complete(fid)
        brain.rc_native("timer", {"seconds": 30, "label": "T"})   # same shape again
        rep = brain.rc_repertoire()
        assert "items" in rep and "suggestion" in rep      # key is always present

    def test_revoke_teaches_a_rejection(self, tmp_path):
        brain = self._brain(tmp_path)
        out = brain.rc_native("interval", {"work": 20, "rest": 10, "label": "I"})
        fid = out["figment_id"]
        before = brain.rc.ranker.completion_rate(fid)
        brain.rc_revoke(fid)
        assert brain.rc.ranker.completion_rate(fid) < before   # rejection lowered it
