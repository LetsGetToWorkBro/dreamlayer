"""quest.py — Saga (the Life Quest Engine): your commitments, as a personal RPG.

Display name: **Saga**. The class stays QuestLog.

A narrative skin on Commitment Drift. The hard part already exists: a
commitment is a living object with a state ladder (blooming → shattered),
behavior signals (nudge/keep/break), and heal-credit momentum. The Quest
layer reads those and tells the story on top:

  quest        one active commitment, titled and ranked by its drift state
  complete     keep() a commitment — award XP, extend the streak, and
               pay a rescue bonus if you saved it from the brink
  abandon      break() a commitment — the streak resets to zero
  tend         nudge() progress — momentum, no XP (XP is for finishing)

XP accrues to a level; consecutive completions build a streak that
multiplies the reward. All of it is a pure function of the drift engine's
own records plus a tiny durable tally (xp, level, streak) — fully
on-device, no new sensors, no cloud. Private commitments never surface
(the drift engine already refuses to observe meta.private events).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .commitment_drift import CommitmentDriftEngine, DriftRecord, _STATES

# state ladder -> quest status the wearer reads
_STATUS = {
    "blooming":  "thriving",
    "healthy":   "on track",
    "drifting":  "slipping",
    "cracking":  "in peril",
    "shattered": "failed",
}

BASE_XP = 50            # a completion's floor reward
RESCUE_XP = 40          # saved from cracking/drifting at the last moment
STREAK_XP = 12          # per prior link in the streak
TALLY_FILE = "quest_log.json"


# leveling + ranks are shared with the Brain-hosted Saga profile (saga.py),
# so the glasses reward cards and the phone profile speak the same language.
from ..saga import (level_for_xp, xp_floor as _xp_floor, rank_for_level,
                    _BY_ID as _SAGA_BY_ID)

# quest-category achievements the completion RPG can award (themed in saga.py)
ACHIEVEMENTS_ORDER = ["keeper", "from_the_brink", "unbroken", "relentless", "devoted"]
_ACH_BY_ID = _SAGA_BY_ID


def _earned(tally: dict) -> set[str]:
    """Which quest achievement ids the lifetime tally qualifies for."""
    got: set[str] = set()
    if tally.get("completed", 0) >= 1:    got.add("keeper")
    if tally.get("rescues", 0) >= 1:      got.add("from_the_brink")
    if tally.get("best_streak", 0) >= 5:  got.add("unbroken")
    if tally.get("best_streak", 0) >= 10: got.add("relentless")
    if tally.get("completed", 0) >= 25:   got.add("devoted")
    return got


@dataclass
class Quest:
    """One commitment, seen as a quest."""
    subject: str
    title: str
    status: str                 # thriving | on track | slipping | in peril | failed | complete
    progress: float             # 0..1 toward safe completion (1 - decay)
    reward_xp: int              # what completing it now would pay
    state: str                  # raw drift state

    def to_hud_card(self) -> dict:
        color = {
            "thriving":  "accent_success", "on track": "accent_memory",
            "slipping":  "accent_attention", "in peril": "accent_attention",
            "failed":    "accent_error", "complete": "accent_success",
        }.get(self.status, "text_primary")
        bars = max(0, min(10, round(self.progress * 10)))
        return {
            "type": "QuestCard",
            "dismiss_ms": 4000,
            "eyebrow": "QUEST",
            "primary": self.title,
            "detail": self.status,
            "meter": "▮" * bars + "▯" * (10 - bars),
            "footer": f"+{self.reward_xp} XP",
            "color": color,
            "lines": ["QUEST", self.title, self.status,
                      "▮" * bars + "▯" * (10 - bars)],
        }


@dataclass
class QuestReward:
    """The payout when a quest completes."""
    subject: str
    xp: int
    total_xp: int
    level: int
    leveled_up: bool
    streak: int
    rescued: bool
    rank: str = "Novice"
    new_rank: bool = False                        # crossed into a new rank band
    new_achievements: list = field(default_factory=list)   # names unlocked now

    def to_hud_card(self) -> dict:
        head = ("RANK UP" if self.new_rank else
                "LEVEL UP" if self.leveled_up else "QUEST COMPLETE")
        lines = [head, f"+{self.xp} XP"]
        if self.streak >= 2:
            lines.append(f"{self.streak}× streak")
        if self.rescued:
            lines.append("rescued from the brink")
        for a in self.new_achievements:
            lines.append(f"★ {a}")
        detail = f"{self.rank} · Level {self.level}"
        return {
            "type": "QuestRewardCard",
            "dismiss_ms": 6000 if (self.new_rank or self.new_achievements) else 5000,
            "eyebrow": head,
            "primary": f"+{self.xp} XP",
            "detail": detail,
            "footer": (f"★ {self.new_achievements[0]}" if self.new_achievements
                       else f"{self.streak}× streak" if self.streak >= 2 else ""),
            "color": "accent_success",
            "leveled_up": self.leveled_up,
            "new_rank": self.new_rank,
            "rank": self.rank,
            "achievements": list(self.new_achievements),
            "lines": lines,
        }


@dataclass
class QuestStats:
    xp: int
    level: int
    streak: int
    level_progress: float       # 0..1 toward the next level
    rank: str = "Novice"
    xp_to_next: int = 0         # XP remaining to the next level
    best_streak: int = 0
    completed: int = 0
    abandoned: int = 0
    rescues: int = 0
    achievements: list = field(default_factory=list)   # unlocked names


class QuestLog:
    """Reads Commitment Drift; keeps a durable XP / level / streak tally."""

    def __init__(self, drift: CommitmentDriftEngine,
                 vault_dir: Optional[Path | str] = None, now_fn=None):
        self._drift = drift
        self._now = now_fn or time.time
        self._vault = Path(vault_dir) if vault_dir else None
        self.xp = 0
        self.streak = 0
        # lifetime tallies + unlocked achievements (durable, on-device)
        self.best_streak = 0
        self.completed = 0
        self.abandoned = 0
        self.rescues = 0
        self.achievements: set[str] = set()
        if self._vault:
            self._load()

    def _tally(self) -> dict:
        return {"completed": self.completed, "rescues": self.rescues,
                "best_streak": self.best_streak, "level": level_for_xp(self.xp)}

    # -- reading the quests ---------------------------------------------

    def quests(self, now: Optional[float] = None) -> list[Quest]:
        now = now if now is not None else self._now()
        self._drift.tick(now=now)
        out: list[Quest] = []
        for rec in self._drift.all_records():
            if rec.resolved == "kept":
                continue                      # completed quests leave the log
            out.append(self._as_quest(rec))
        # most-imperilled first: the quest about to fail wants your eyes
        out.sort(key=lambda q: -_STATES.index(q.state))
        return out

    def _as_quest(self, rec: DriftRecord) -> Quest:
        title = (rec.event.summary or "a promise").strip()
        return Quest(
            subject=title,
            title=title[:24],
            status="failed" if rec.resolved == "broken"
            else _STATUS.get(rec.state, "on track"),
            progress=max(0.0, 1.0 - rec.decay),
            reward_xp=self._reward_preview(rec),
            state="shattered" if rec.resolved == "broken" else rec.state,
        )

    # -- the verbs -------------------------------------------------------

    def complete(self, subject: str,
                 now: Optional[float] = None) -> Optional[QuestReward]:
        now = now if now is not None else self._now()
        self._drift.tick(now=now)             # freshen states at `now`
        rec = self._drift._find(subject)
        if rec is None or rec.resolved is not None:
            return None
        rescued = rec.state in ("drifting", "cracking")
        self._drift.keep(subject, now=now)

        self.streak += 1
        self.completed += 1
        if rescued:
            self.rescues += 1
        self.best_streak = max(self.best_streak, self.streak)
        before = level_for_xp(self.xp)
        gain = (BASE_XP + (RESCUE_XP if rescued else 0)
                + STREAK_XP * (self.streak - 1))
        self.xp += gain
        after = level_for_xp(self.xp)
        # newly-unlocked achievements (diff the lifetime tally against what we had)
        earned = _earned(self._tally())
        fresh = earned - self.achievements
        self.achievements |= earned
        self._save()
        return QuestReward(
            subject=subject, xp=gain, total_xp=self.xp, level=after,
            leveled_up=after > before, streak=self.streak, rescued=rescued,
            rank=rank_for_level(after),
            new_rank=rank_for_level(after) != rank_for_level(before),
            new_achievements=[_ACH_BY_ID[i].name for i in ACHIEVEMENTS_ORDER
                              if i in fresh])

    def abandon(self, subject: str, now: Optional[float] = None) -> bool:
        now = now if now is not None else self._now()
        rec = self._drift.break_(subject, now=now)
        if rec is None:
            return False
        self.streak = 0                       # the chain breaks
        self.abandoned += 1
        self._save()
        return True

    def tend(self, subject: str, now: Optional[float] = None):
        """Progress without finishing — momentum only, no XP."""
        return self._drift.nudge(subject, now=now)

    # -- stats -----------------------------------------------------------

    def stats(self) -> QuestStats:
        level = level_for_xp(self.xp)
        floor, ceil = _xp_floor(level), _xp_floor(level + 1)
        span = max(1, ceil - floor)
        names = [_ACH_BY_ID[i].name for i in ACHIEVEMENTS_ORDER if i in self.achievements]
        return QuestStats(
            xp=self.xp, level=level, streak=self.streak,
            level_progress=min(1.0, (self.xp - floor) / span),
            rank=rank_for_level(level), xp_to_next=max(0, ceil - self.xp),
            best_streak=self.best_streak, completed=self.completed,
            abandoned=self.abandoned, rescues=self.rescues, achievements=names)

    def _reward_preview(self, rec: DriftRecord) -> int:
        rescued = rec.state in ("drifting", "cracking")
        return (BASE_XP + (RESCUE_XP if rescued else 0)
                + STREAK_XP * self.streak)

    # -- persistence -----------------------------------------------------

    def _path(self) -> Path:
        assert self._vault is not None   # _path is only read on the vault-backed arc
        return self._vault / TALLY_FILE

    def _load(self) -> None:
        p = self._path()
        if p.exists():
            try:
                d = json.loads(p.read_text())
                self.xp = int(d.get("xp", 0))
                self.streak = int(d.get("streak", 0))
                self.best_streak = int(d.get("best_streak", self.streak))
                self.completed = int(d.get("completed", 0))
                self.abandoned = int(d.get("abandoned", 0))
                self.rescues = int(d.get("rescues", 0))
                self.achievements = set(d.get("achievements", []))
            except (ValueError, KeyError, json.JSONDecodeError):
                pass

    def _save(self) -> None:
        if not self._vault:
            return
        self._vault.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps(
            {"xp": self.xp, "streak": self.streak,
             "best_streak": self.best_streak, "completed": self.completed,
             "abandoned": self.abandoned, "rescues": self.rescues,
             "achievements": sorted(self.achievements),
             "rank": rank_for_level(level_for_xp(self.xp)),
             "level": level_for_xp(self.xp)}))
