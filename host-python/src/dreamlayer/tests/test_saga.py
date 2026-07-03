"""test_saga.py — DreamLayer's progression: themed ranks, a capped level, and
ecosystem achievements with what/how/status.
"""
from __future__ import annotations

from dreamlayer import saga


def test_levels_cap_at_max():
    assert saga.level_for_xp(0) == 1
    assert saga.level_for_xp(100) == 2
    assert saga.level_for_xp(10**9) == saga.MAX_LEVEL     # never exceeds the cap
    assert saga.xp_to_next(10**9) == 0                     # nothing left at the summit


def test_themed_rank_ladder():
    assert saga.rank_for_level(1) == "Sleeper"
    assert saga.rank_for_level(10) == "Seer"
    assert saga.rank_for_level(saga.MAX_LEVEL) == "Architect of Memory"
    nxt = saga.next_rank(1)
    assert nxt["title"] == "Dreamer"
    assert saga.next_rank(saga.MAX_LEVEL) is None          # nothing above the summit


def test_explore_achievement_unlocks_and_awards_xp():
    p = saga.SagaProfile()
    fresh = p.record("calendar")
    assert "Timekeeper" in fresh and p.xp > 0
    assert p.record("calendar") == []                      # already earned, no repeat


def test_counted_achievement_tracks_progress():
    p = saga.SagaProfile()
    # "Devoted" needs 25 completed; a few completions show progress, not unlock
    for _ in range(3):
        p.record("quest_done")
    snap = {a["id"]: a for a in p.snapshot()["achievements"]}
    assert snap["keeper"]["unlocked"] is True              # 1 completion → Keeper
    assert snap["devoted"]["unlocked"] is False
    assert snap["devoted"]["progress"] == 3 and snap["devoted"]["target"] == 25


def test_streak_uses_absolute_count():
    p = saga.SagaProfile()
    assert p.record("streak", count=5) and "Unbroken" in [
        a["name"] for a in p.snapshot()["achievements"] if a["unlocked"]]


def test_level_milestones_unlock_from_xp():
    p = saga.SagaProfile()
    p.xp = saga.xp_floor(5)                                 # jump to level 5
    fresh = p.note_level(saga.level_for_xp(p.xp))
    assert "First Light" in fresh and "Waking" in fresh    # L2 + L5 milestones


def test_snapshot_carries_what_how_and_status():
    p = saga.SagaProfile()
    snap = p.snapshot()
    assert snap["rank"] == "Sleeper" and snap["max_level"] == saga.MAX_LEVEL
    assert snap["total_count"] == len(saga.ACHIEVEMENTS)
    tk = next(a for a in snap["achievements"] if a["id"] == "timekeeper")
    assert tk["what"] and tk["how"] and tk["category"] == "explore"
    assert tk["unlocked"] is False and tk["target"] == 1


def test_profile_persists(tmp_path):
    p = saga.SagaProfile(vault_dir=tmp_path)
    p.record("cloud"); p.record("pair")
    reborn = saga.SagaProfile(vault_dir=tmp_path)
    assert reborn.xp == p.xp
    unlocked = {a["id"] for a in reborn.snapshot()["achievements"] if a["unlocked"]}
    assert "reach_beyond" in unlocked and "entangled" in unlocked


def test_every_feature_has_a_badge():
    # the ecosystem features the app/panel record should each map to an achievement
    events = {a.event for a in saga.ACHIEVEMENTS if a.category == "explore"}
    for feature in ("pair", "mac", "cloud", "incognito", "calendar", "contacts",
                    "reminders", "brief", "recall", "focus", "rewind", "hark",
                    "model", "backup", "folder", "oracle_wake", "dossier"):
        assert feature in events, f"no badge for {feature}"
