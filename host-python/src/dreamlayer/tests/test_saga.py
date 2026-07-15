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
                    "model", "backup", "folder", "juno_wake", "dossier"):
        assert feature in events, f"no badge for {feature}"


def test_forget_erases_one_events_usage_trail(tmp_path):
    """Privacy erase path (audit 2026-07-14): forgetting a privacy-sensitive
    event scrubs its counter + badge from the persisted file, leaving unrelated
    progress intact."""
    p = saga.SagaProfile(vault_dir=tmp_path)
    p.record("incognito")                        # unlocks "Veiled", writes a trail
    p.record("calendar")                         # unrelated, must survive
    assert "incognito" in p.progress
    unlocked = {a["id"] for a in p.snapshot()["achievements"] if a["unlocked"]}
    assert "veiled" in unlocked

    assert p.forget("incognito") is True
    assert "incognito" not in p.progress         # counter gone
    still = {a["id"] for a in p.snapshot()["achievements"] if a["unlocked"]}
    assert "veiled" not in still                  # badge relocked
    assert "timekeeper" in still                  # unrelated survives

    # and it's persisted — a reborn profile no longer knows about incognito
    reborn = saga.SagaProfile(vault_dir=tmp_path)
    assert "incognito" not in reborn.progress
    assert "veiled" not in reborn.unlocked
    # forgetting something never recorded is a no-op
    assert reborn.forget("never-happened") is False


def test_forget_all_wipes_everything_and_removes_the_file(tmp_path):
    p = saga.SagaProfile(vault_dir=tmp_path)
    p.record("cloud"); p.record("pair"); p.record("recall")
    assert (tmp_path / saga.SAGA_FILE).exists()

    p.forget_all()
    assert p.xp == 0 and p.unlocked == set() and p.progress == {}
    assert not (tmp_path / saga.SAGA_FILE).exists()   # durable file removed
    # a reborn profile starts clean
    reborn = saga.SagaProfile(vault_dir=tmp_path)
    assert reborn.xp == 0 and reborn.unlocked == set()


def test_corrupt_save_file_recovers_to_defaults_with_a_warning(tmp_path, caplog):
    """A truncated/corrupt saga.json must recover to defaults but on the record —
    not a silent total-progress loss (audit 2026-07-14)."""
    import logging
    (tmp_path / saga.SAGA_FILE).write_text("{not: valid json,,,")
    with caplog.at_level(logging.WARNING, logger="dreamlayer.saga"):
        p = saga.SagaProfile(vault_dir=tmp_path)
    assert p.xp == 0 and p.unlocked == set() and p.progress == {}
    assert any("unreadable" in r.message for r in caplog.records)


def test_concurrent_saves_never_publish_a_torn_file(tmp_path):
    """Re-audit 2026-07-15: the atomic-write fix used a FIXED tmp name with no
    lock, so two threaded writers could interleave into the one tmp before
    either os.replace and publish a truncated saga.json that _load resets to
    zero. A per-writer tmp + a lock closes it: many concurrent records leave a
    valid file and no stray tmp."""
    import json as _json
    import threading

    sp = saga.SagaProfile(tmp_path)
    errs = []

    def worker():
        try:
            for _ in range(40):
                sp.record("cloud")            # each record() persists via _save
        except Exception as exc:              # a torn write / race would raise
            errs.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errs, errs
    # the published file is always complete, valid JSON — never a torn write
    data = _json.loads((tmp_path / saga.SAGA_FILE).read_text())
    assert isinstance(data, dict) and "xp" in data
    # and no per-writer tmp leaked
    assert list(tmp_path.glob("*.tmp")) == []
