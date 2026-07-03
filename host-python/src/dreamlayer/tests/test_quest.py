"""test_quest.py — the Life Quest Engine over Commitment Drift."""
from __future__ import annotations

import pytest

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.orchestrator.commitment_drift import CommitmentDriftEngine
from dreamlayer.orchestrator.quest import (
    QuestLog, level_for_xp, BASE_XP, RESCUE_XP, STREAK_XP,
)

BASE = 1000.0
H = 3600.0


def ring_with(*tasks) -> SemanticRingBuffer:
    ring = SemanticRingBuffer(capacity=50)
    for summary, due in tasks:
        ring.append(MemoryEvent(kind="task", summary=summary, confidence=0.8,
                                meta={"due": due}), ts=BASE)
    return ring


def log_for(*tasks, vault=None):
    eng = CommitmentDriftEngine(ring_with(*tasks))
    return QuestLog(eng, vault_dir=vault, now_fn=lambda: BASE)


class TestLevels:
    def test_level_thresholds(self):
        assert level_for_xp(0) == 1
        assert level_for_xp(99) == 1
        assert level_for_xp(100) == 2
        assert level_for_xp(300) == 3
        assert level_for_xp(600) == 4


class TestQuests:
    def test_quests_mirror_commitments(self):
        log = log_for(("call dentist", "2h"), ("email Sam", "2h"))
        qs = log.quests(now=BASE + 0.1 * H)
        assert len(qs) == 2
        assert {q.title for q in qs} == {"call dentist", "email Sam"}
        assert all(q.status in ("thriving", "on track") for q in qs)

    def test_most_imperilled_first(self):
        log = log_for(("safe task", "10h"), ("urgent task", "2h"))
        qs = log.quests(now=BASE + 1.8 * H)     # urgent is ~90% decayed
        assert qs[0].title == "urgent task"     # in peril sorts to the top
        assert qs[0].status == "in peril"

    def test_completed_quest_leaves_the_log(self):
        log = log_for(("call dentist", "2h"))
        log.complete("dentist", now=BASE + 0.2 * H)
        assert log.quests(now=BASE + 0.3 * H) == []


class TestRewards:
    def test_completion_awards_base_xp_and_streak(self):
        log = log_for(("call dentist", "2h"))
        r = log.complete("dentist", now=BASE + 0.1 * H)
        assert r is not None
        assert r.xp == BASE_XP                   # first, on-time, no streak
        assert r.streak == 1
        assert log.xp == BASE_XP

    def test_streak_multiplies_reward(self):
        log = log_for(("q one", "2h"), ("q two", "2h"), ("q three", "2h"))
        r1 = log.complete("q one", now=BASE)
        r2 = log.complete("q two", now=BASE)
        r3 = log.complete("q three", now=BASE)
        assert (r1.streak, r2.streak, r3.streak) == (1, 2, 3)
        assert r2.xp == BASE_XP + STREAK_XP      # +1 link
        assert r3.xp == BASE_XP + 2 * STREAK_XP

    def test_rescue_bonus_when_saved_from_the_brink(self):
        log = log_for(("call dentist", "2h"))
        r = log.complete("dentist", now=BASE + 1.8 * H)   # cracking
        assert r.rescued is True
        assert r.xp == BASE_XP + RESCUE_XP

    def test_abandon_resets_the_streak(self):
        log = log_for(("q one", "2h"), ("q two", "2h"))
        log.complete("q one", now=BASE)
        assert log.streak == 1
        assert log.abandon("q two", now=BASE) is True
        assert log.streak == 0

    def test_level_up_is_flagged(self):
        # stack enough completions to cross L1->L2 at 100 XP
        log = log_for(("a", "2h"), ("b", "2h"))
        log.complete("a", now=BASE)              # 50 xp, still L1
        r = log.complete("b", now=BASE)          # +62 -> 112 xp, L2
        assert r.leveled_up is True
        assert r.level == 2

    def test_complete_unknown_is_noop(self):
        log = log_for(("call dentist", "2h"))
        assert log.complete("nonexistent", now=BASE) is None
        assert log.xp == 0


class TestStatsAndTend:
    def test_stats_track_progress_to_next_level(self):
        log = log_for(("a", "2h"))
        log.complete("a", now=BASE)              # 50 xp toward the 100 for L2
        s = log.stats()
        assert s.level == 1 and s.xp == 50
        assert 0.4 < s.level_progress < 0.6

    def test_tend_is_progress_without_xp(self):
        log = log_for(("call dentist", "6h"))
        log.tend("dentist", now=BASE + 3 * H)
        assert log.xp == 0                        # tending pays no XP
        # ...but it healed the quest: progress rose above the untended line
        q = next(q for q in log.quests(now=BASE + 3 * H) if "dentist" in q.title)
        assert q.progress > 0.5


class TestPersistence:
    def test_xp_and_streak_survive_reload(self, tmp_path):
        log = log_for(("a", "2h"), vault=tmp_path)
        log.complete("a", now=BASE)
        xp, streak = log.xp, log.streak
        fresh = QuestLog(CommitmentDriftEngine(ring_with(("b", "2h"))),
                         vault_dir=tmp_path, now_fn=lambda: BASE)
        assert fresh.xp == xp and fresh.streak == streak


class TestOrchestratorWiring:
    def _orc(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        return Orchestrator(FakeBridge())

    def test_quest_and_skill_and_consistency_are_wired(self):
        orc = self._orc()
        assert orc.quest is not None and orc.consistency is not None
        # a commitment shows up as a quest and completes for XP + a card
        orc.ring.append(MemoryEvent(kind="task", summary="call dentist",
                                    confidence=0.8, meta={"due": "2h"}), ts=BASE)
        assert any("dentist" in q.title for q in orc.quests(now=BASE))
        reward = orc.complete_quest("dentist", now=BASE)
        assert reward is not None and reward.xp > 0
        assert any(f.get("t") == "card" for f in orc.bridge.raw)

    def test_build_skill_returns_verified_figment(self):
        orc = self._orc()
        fig, report = orc.build_skill("Tea", "1. Boil water\n2. Steep 3 min")
        assert len(fig.scenes) == 2 and report.ok

    def test_consistency_is_veil_gated(self):
        orc = self._orc()
        orc.ring.append(MemoryEvent(kind="memory", summary="the gate is open",
                                    confidence=0.8), ts=BASE)
        orc.privacy.pause()                       # veil down
        assert orc.check_consistency("the gate is closed") is None


class TestRobustQuestSystem:
    def test_ranks_climb_with_level(self):
        from dreamlayer.orchestrator.quest import rank_for_level
        assert rank_for_level(1) == "Sleeper"
        assert rank_for_level(6) == "Lucid"
        assert rank_for_level(28) == "Architect of Memory"
        assert rank_for_level(100) == "Architect of Memory"   # caps at the top band

    def test_completion_tallies_and_first_achievement(self):
        log = log_for(("send the invoice", "1h"))
        reward = log.complete("send the invoice", now=BASE)
        assert reward.rank == "Sleeper"
        assert "Keeper" in reward.new_achievements       # unlocked on first completion
        s = log.stats()
        assert s.completed == 1 and s.best_streak == 1
        assert "Keeper" in s.achievements
        assert s.xp_to_next > 0

    def test_rescue_unlocks_rescuer_and_counts(self):
        log = log_for(("sign the lease", "2h"))
        # complete it while it's cracking (~90% decayed) — a last-moment rescue
        reward = log.complete("sign the lease", now=BASE + 1.8 * H)
        assert reward.rescued and "From the Brink" in reward.new_achievements
        assert log.stats().rescues == 1

    def test_best_streak_survives_a_reset(self):
        log = log_for(("a", "1h"), ("b", "1h"), ("c", "1h"))
        log.complete("a", now=BASE); log.complete("b", now=BASE)  # streak → 2
        assert log.stats().best_streak == 2
        log.abandon("c", now=BASE)                                 # streak resets
        assert log.stats().streak == 0 and log.stats().best_streak == 2
        assert log.stats().abandoned == 1

    def test_tally_and_achievements_persist(self, tmp_path):
        log = log_for(("send the invoice", "1h"), vault=tmp_path)
        log.complete("send the invoice", now=BASE)
        reborn = QuestLog(CommitmentDriftEngine(ring_with(("x", "1h"))),
                          vault_dir=tmp_path, now_fn=lambda: BASE)
        assert reborn.completed == 1 and reborn.best_streak == 1
        assert "keeper" in reborn.achievements
        # a re-earned achievement doesn't re-announce
        r2 = reborn.complete("x", now=BASE)
        assert "Keeper" not in r2.new_achievements

    def test_reward_card_shows_rank_and_achievement(self):
        log = log_for(("send the invoice", "1h"))
        card = log.complete("send the invoice", now=BASE).to_hud_card()
        assert "Sleeper" in card["detail"]
        assert any("Keeper" in ln for ln in card["lines"])
