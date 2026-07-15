"""saga.py — DreamLayer's progression: ranks, levels, and achievements.

Saga is the game layer over living with the Halo. You climb from **Sleeper** to
**Architect of Memory** as you keep promises (the quest RPG) *and* explore the
ecosystem — pairing, syncing, waking Juno, recalling a face. Every few levels
is a milestone; every feature has a badge, so the game nudges you to try
everything.

This module is the single source of truth, shared by the hub's quest engine and
the Brain-hosted profile the phone shows. Pure and fully on-device: XP comes
from unlocking achievements and keeping quests; a small durable JSON is the
only state.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("dreamlayer.saga")

MAX_LEVEL = 30
SAGA_FILE = "saga.json"


# -- levels ------------------------------------------------------------------

def _cumulative(level: int) -> int:
    """XP needed to *reach* `level` (L1@0, L2@100, L3@300, …)."""
    return 100 * (level - 1) * level // 2


def level_for_xp(xp: int) -> int:
    """Level for a given XP, widening as it climbs and capped at MAX_LEVEL."""
    lvl = 1
    while lvl < MAX_LEVEL and xp >= _cumulative(lvl + 1):
        lvl += 1
    return lvl


def xp_floor(level: int) -> int:
    return _cumulative(level)


def xp_to_next(xp: int) -> int:
    """XP remaining to the next level (0 at MAX_LEVEL)."""
    lvl = level_for_xp(xp)
    if lvl >= MAX_LEVEL:
        return 0
    return max(0, _cumulative(lvl + 1) - xp)


# -- ranks — waking into awareness -------------------------------------------

RANKS = [
    (1,  "Sleeper"),
    (3,  "Dreamer"),
    (6,  "Lucid"),
    (10, "Seer"),
    (15, "Juno"),
    (21, "Luminary"),
    (28, "Architect of Memory"),
]


def rank_for_level(level: int) -> str:
    title = RANKS[0][1]
    for lvl, name in RANKS:
        if level >= lvl:
            title = name
    return title


def next_rank(level: int):
    """(level_at, title) of the next rank up, or None at the summit."""
    for lvl, name in RANKS:
        if lvl > level:
            return {"level": lvl, "title": name}
    return None


# -- achievements ------------------------------------------------------------

@dataclass(frozen=True)
class Achievement:
    id: str
    name: str
    what: str           # what it is
    how: str            # how to earn it
    category: str       # "milestone" | "quest" | "explore"
    target: int = 1     # count needed (1 = a one-shot)
    xp: int = 0         # awarded on unlock
    event: str = ""     # record() key that advances it ("" = level milestone)
    level: int = 0      # for milestones: the level that unlocks it


ACHIEVEMENTS = [
    # -- milestones (every few levels) --------------------------------------
    Achievement("first_light", "First Light", "Awareness dawns.",
                "Reach level 2.", "milestone", level=2),
    Achievement("waking", "Waking", "The dream sharpens.",
                "Reach level 5.", "milestone", level=5),
    Achievement("lucid", "Lucid", "You know you're dreaming.",
                "Reach level 10.", "milestone", level=10),
    Achievement("farsight", "Farsight", "You see further than the day.",
                "Reach level 15.", "milestone", level=15),
    Achievement("junos_eye", "Juno's Eye", "Knowing before asking.",
                "Reach level 20.", "milestone", level=20),
    Achievement("luminous", "Luminous", "You light the room.",
                "Reach level 25.", "milestone", level=25),
    Achievement("architect", "Architect of Memory", "Mastery of the layer.",
                "Reach level 30 — the summit.", "milestone", level=MAX_LEVEL),
    # -- quests (the promise-keeping RPG) -----------------------------------
    Achievement("keeper", "Keeper", "You keep your word.",
                "Complete your first quest.", "quest", 1, 80, "quest_done"),
    Achievement("from_the_brink", "From the Brink", "Saved at the last moment.",
                "Complete a quest that was about to fail.", "quest", 1, 120, "quest_rescue"),
    Achievement("unbroken", "Unbroken", "A chain of kept promises.",
                "Reach a 5× completion streak.", "quest", 5, 150, "streak"),
    Achievement("relentless", "Relentless", "Nothing slips.",
                "Reach a 10× completion streak.", "quest", 10, 300, "streak"),
    Achievement("devoted", "Devoted", "A life of follow-through.",
                "Complete 25 quests.", "quest", 25, 400, "quest_done"),
    # -- explore the ecosystem (one per feature) ----------------------------
    Achievement("entangled", "Entangled", "Phone, brain, and glasses as one.",
                "Pair your phone with the glasses.", "explore", 1, 150, "pair"),
    Achievement("second_mind", "Second Mind", "A bigger brain at home.",
                "Connect your Mac mini brain.", "explore", 1, 150, "mac"),
    Achievement("reach_beyond", "Reach Beyond", "The frontier, when you need it.",
                "Turn on the cloud tier.", "explore", 1, 150, "cloud"),
    Achievement("veiled", "Veiled", "Off the record.",
                "Slip into Incognito once.", "explore", 1, 150, "incognito"),
    Achievement("hey_juno", "Hey Juno", "You spoke; it listened.",
                "Wake Juno by voice.", "explore", 1, 150, "juno_wake"),
    Achievement("face_to_name", "Face to Name", "You know them again.",
                "Surface a person's dossier.", "explore", 1, 150, "dossier"),
    Achievement("total_recall", "Total Recall", "Your whole mind, searchable.",
                "Ask your Brain a question.", "explore", 1, 150, "recall"),
    Achievement("dawn", "Dawn", "The day, at a glance.",
                "Receive a morning brief.", "explore", 1, 150, "brief"),
    Achievement("timekeeper", "Timekeeper", "Your calendar, on your face.",
                "Sync your calendar.", "explore", 1, 150, "calendar"),
    Achievement("inner_circle", "Inner Circle", "Dossiers that fill themselves.",
                "Sync your contacts.", "explore", 1, 150, "contacts"),
    Achievement("the_list", "The List", "To-dos that follow you.",
                "Sync your reminders.", "explore", 1, 150, "reminders"),
    Achievement("deep_focus", "Deep Focus", "The world turned down.",
                "Enter Focus mode.", "explore", 1, 150, "focus"),
    Achievement("rewind", "Rewind", "Scrub back through the day.",
                "Open Rewind.", "explore", 1, 150, "rewind"),
    Achievement("listen", "Listen", "Juno tapped your shoulder.",
                "Get a “Listen!” from Juno.", "explore", 1, 150, "hark"),
    Achievement("local_mind", "Local Mind", "Smarts with no cord to the cloud.",
                "Pull a local model.", "explore", 1, 150, "model"),
    Achievement("the_vault", "The Vault", "Nothing lost.",
                "Back up your Brain.", "explore", 1, 150, "backup"),
    Achievement("well_read", "Well-Read", "Your own library, indexed.",
                "Add a knowledge folder.", "explore", 1, 150, "folder"),
]

_BY_ID = {a.id: a for a in ACHIEVEMENTS}
_BY_EVENT: dict[str, list[Achievement]] = {}
for _a in ACHIEVEMENTS:
    if _a.event:
        _BY_EVENT.setdefault(_a.event, []).append(_a)


class SagaProfile:
    """The durable game state: XP + which achievements are unlocked and how far
    along the counted ones are. XP is earned by unlocking achievements."""

    def __init__(self, vault_dir=None):
        self._vault = Path(vault_dir) if vault_dir else None
        self.xp = 0
        self.unlocked: set[str] = set()
        self.progress: dict[str, int] = {}     # event-id → count so far
        import threading
        self._save_lock = threading.Lock()     # serialize concurrent _save()
        if self._vault:
            self._load()

    # -- earning ---------------------------------------------------------

    def record(self, event: str, n: int = 1, count: int | None = None) -> list[str]:
        """Report ecosystem/quest activity. `count` sets an absolute value (e.g.
        a streak of 5); otherwise progress increments by `n`. Returns the names
        of any achievements newly unlocked."""
        fresh: list[str] = []
        cur = count if count is not None else self.progress.get(event, 0) + n
        # Cap the stored count at the highest target this event can unlock, so
        # saga.json stops accumulating an uncapped usage-frequency trail of
        # privacy-sensitive events (how many times you went incognito / recalled
        # / opened a dossier) that rides along in a Brain backup (audit
        # 2026-07-14). Past the max target the achievement is already earned.
        cap = max((a.target for a in _BY_EVENT.get(event, [])), default=1)
        self.progress[event] = min(cap, max(self.progress.get(event, 0), cur))
        for a in _BY_EVENT.get(event, []):
            if a.id not in self.unlocked and self.progress[event] >= a.target:
                self._unlock(a, fresh)
        self._save()
        return fresh

    # -- forgetting — the erase path for the usage trail -----------------

    def forget(self, event: str) -> bool:
        """Erase the persisted usage trail for one event: its frequency counter
        and any explore/quest badge earned from it (with the XP it awarded), so
        no residue of a privacy-sensitive activity (incognito / recall / dossier
        / cloud) lingers in ``saga.json`` — a file a `backup` achievement implies
        can leave the device. Level milestones are a coarse aggregate (they name
        no feature) and are deliberately left. Returns True if anything was
        erased; persists the result (audit 2026-07-14: a saga store with no erase
        path is a privacy gap)."""
        changed = event in self.progress
        self.progress.pop(event, None)
        for a in _BY_EVENT.get(event, []):
            if a.id in self.unlocked:
                self.unlocked.discard(a.id)
                self.xp = max(0, self.xp - a.xp)
                changed = True
        if changed:
            self._save()
        return changed

    def forget_all(self) -> None:
        """The nuclear erase: drop all XP, badges, and counters and remove the
        durable file, mirroring the engine's erase-everything path for saga
        state. Serialised against ``_save`` so it can't race a concurrent write."""
        with self._save_lock:
            self.xp = 0
            self.unlocked = set()
            self.progress = {}
            if self._vault:
                p = self._path()
                try:
                    if p.exists():
                        p.unlink()
                except OSError as exc:
                    log.warning("saga: could not remove %s: %s", p, exc)

    def note_level(self, level: int) -> list[str]:
        """Unlock level-milestone badges up to `level`."""
        fresh: list[str] = []
        for a in ACHIEVEMENTS:
            if a.category == "milestone" and a.id not in self.unlocked \
                    and level >= a.level:
                self._unlock(a, fresh)
        if fresh:
            self._save()
        return fresh

    def _unlock(self, a: Achievement, fresh: list[str]) -> None:
        self.unlocked.add(a.id)
        self.xp += a.xp
        fresh.append(a.name)
        # a fresh XP total may cross a level → unlock milestones (no XP, no loop)
        for m in ACHIEVEMENTS:
            if m.category == "milestone" and m.id not in self.unlocked \
                    and level_for_xp(self.xp) >= m.level:
                self.unlocked.add(m.id)
                fresh.append(m.name)

    # -- reading ---------------------------------------------------------

    def _count_for(self, a: Achievement) -> int:
        if a.category == "milestone":
            return min(level_for_xp(self.xp), a.level)
        return min(self.progress.get(a.event, 0), a.target)

    def snapshot(self) -> dict:
        level = level_for_xp(self.xp)
        achs = []
        for a in ACHIEVEMENTS:
            unlocked = a.id in self.unlocked
            target = a.level if a.category == "milestone" else a.target
            progress = target if unlocked else self._count_for(a)
            achs.append({
                "id": a.id, "name": a.name, "what": a.what, "how": a.how,
                "category": a.category, "xp": a.xp,
                "unlocked": unlocked, "progress": progress, "target": target,
            })
        return {
            "xp": self.xp, "level": level, "max_level": MAX_LEVEL,
            "rank": rank_for_level(level), "next_rank": next_rank(level),
            "xp_to_next": xp_to_next(self.xp),
            "level_floor": xp_floor(level), "level_ceil": xp_floor(level + 1),
            "unlocked_count": len(self.unlocked), "total_count": len(ACHIEVEMENTS),
            "achievements": achs,
        }

    # -- persistence -----------------------------------------------------

    def _path(self) -> Path:
        return self._vault / SAGA_FILE

    def _load(self) -> None:
        p = self._path()
        if p.exists():
            try:
                d = json.loads(p.read_text())
                self.xp = int(d.get("xp", 0))
                self.unlocked = set(d.get("unlocked", []))
                self.progress = {k: int(v) for k, v in (d.get("progress") or {}).items()}
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                # a corrupt/truncated saga.json must not silently reset progress
                # to zero with no trace — recover to defaults, but on the record
                # (audit 2026-07-14: _load swallowed all errors → invisible total
                # loss of progression).
                log.warning("saga: ignoring unreadable %s (%s); starting fresh",
                            p, exc)

    def _save(self) -> None:
        if not self._vault:
            return
        self._vault.mkdir(parents=True, exist_ok=True)
        # atomic write (temp + os.replace) so a crash mid-write — or the hub
        # quest engine and the Brain profile writing at once — can't leave a
        # truncated saga.json that _load silently resets to zero (audit
        # 2026-07-14). The first pass used a FIXED tmp name with NO lock, so the
        # very concurrency it names could still interleave two writers into the
        # one tmp before either os.replace — os.replace makes the rename atomic,
        # not the tmp contents. A per-writer unique tmp + a lock closes it
        # (re-audit 2026-07-15).
        import os
        payload = json.dumps({
            "xp": self.xp, "level": level_for_xp(self.xp),
            "rank": rank_for_level(level_for_xp(self.xp)),
            "unlocked": sorted(self.unlocked), "progress": self.progress})
        path = self._path()
        with self._save_lock:
            tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            tmp.write_text(payload)
            os.replace(tmp, path)
