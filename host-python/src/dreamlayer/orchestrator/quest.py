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


def level_for_xp(xp: int) -> int:
    """Levels widen as they climb: L needs 100*L*(L-1)/2 cumulative XP, so
    L1@0, L2@100, L3@300, L4@600, … — early wins come fast, mastery slow."""
    lvl = 1
    while xp >= 100 * lvl * (lvl + 1) // 2:
        lvl += 1
    return lvl


def _xp_floor(level: int) -> int:
    return 100 * (level - 1) * level // 2


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

    def to_hud_card(self) -> dict:
        head = "LEVEL UP" if self.leveled_up else "QUEST COMPLETE"
        lines = [head, f"+{self.xp} XP"]
        if self.streak >= 2:
            lines.append(f"{self.streak}× streak")
        if self.rescued:
            lines.append("rescued from the brink")
        return {
            "type": "QuestRewardCard",
            "dismiss_ms": 5000,
            "eyebrow": head,
            "primary": f"+{self.xp} XP",
            "detail": f"Level {self.level}",
            "footer": (f"{self.streak}× streak" if self.streak >= 2 else ""),
            "color": "accent_success",
            "leveled_up": self.leveled_up,
            "lines": lines,
        }


@dataclass
class QuestStats:
    xp: int
    level: int
    streak: int
    level_progress: float       # 0..1 toward the next level


class QuestLog:
    """Reads Commitment Drift; keeps a durable XP / level / streak tally."""

    def __init__(self, drift: CommitmentDriftEngine,
                 vault_dir: Optional[Path | str] = None, now_fn=None):
        self._drift = drift
        self._now = now_fn or time.time
        self._vault = Path(vault_dir) if vault_dir else None
        self.xp = 0
        self.streak = 0
        if self._vault:
            self._load()

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
        before = level_for_xp(self.xp)
        gain = (BASE_XP + (RESCUE_XP if rescued else 0)
                + STREAK_XP * (self.streak - 1))
        self.xp += gain
        after = level_for_xp(self.xp)
        self._save()
        return QuestReward(
            subject=subject, xp=gain, total_xp=self.xp, level=after,
            leveled_up=after > before, streak=self.streak, rescued=rescued)

    def abandon(self, subject: str, now: Optional[float] = None) -> bool:
        now = now if now is not None else self._now()
        rec = self._drift.break_(subject, now=now)
        if rec is None:
            return False
        self.streak = 0                       # the chain breaks
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
        return QuestStats(xp=self.xp, level=level, streak=self.streak,
                          level_progress=min(1.0, (self.xp - floor) / span))

    def _reward_preview(self, rec: DriftRecord) -> int:
        rescued = rec.state in ("drifting", "cracking")
        return (BASE_XP + (RESCUE_XP if rescued else 0)
                + STREAK_XP * self.streak)

    # -- persistence -----------------------------------------------------

    def _path(self) -> Path:
        return self._vault / TALLY_FILE

    def _load(self) -> None:
        p = self._path()
        if p.exists():
            try:
                d = json.loads(p.read_text())
                self.xp = int(d.get("xp", 0))
                self.streak = int(d.get("streak", 0))
            except (ValueError, KeyError, json.JSONDecodeError):
                pass

    def _save(self) -> None:
        if not self._vault:
            return
        self._vault.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps(
            {"xp": self.xp, "streak": self.streak,
             "level": level_for_xp(self.xp)}))
