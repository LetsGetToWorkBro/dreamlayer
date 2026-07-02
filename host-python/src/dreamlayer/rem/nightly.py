"""rem/nightly.py — NightWatch: when the glasses actually dream.

REM runs at night, on the charger. The NightWatch is the gate: it
answers "should we dream now?" and, when yes, runs one cycle over the
day, applies the reel to the durable RetrievalBias, and writes the
morning reel so the phone has something to show over coffee.

Conditions (all must hold):
  charging          — the phone says so; dreaming is a charger activity
  night             — local hour inside [NIGHT_FROM, NIGHT_UNTIL)
  rested            — at least MIN_GAP_H since the last cycle (stamped
                      durably in the vault directory)

Everything stays deterministic: the night's seed is the day number, so
re-running an interrupted night reproduces the same dreams.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .bias import RetrievalBias
from .cycle import DreamReel, REMCycle
from .reel import render_reel

NIGHT_FROM = 22        # 22:00 …
NIGHT_UNTIL = 6        # … 06:00
MIN_GAP_H = 20.0
STAMP_FILE = "rem_last_night.json"


def _is_night(hour: int) -> bool:
    return hour >= NIGHT_FROM or hour < NIGHT_UNTIL


class NightWatch:
    def __init__(self, vault_dir: Path | str, now_fn=None) -> None:
        self.vault_dir = Path(vault_dir)
        self._now = now_fn or time.time
        self._stamp_path = self.vault_dir / STAMP_FILE

    # -- the gate -----------------------------------------------------------

    def last_night(self) -> float:
        if self._stamp_path.exists():
            try:
                return float(json.loads(
                    self._stamp_path.read_text())["ts"])
            except (ValueError, KeyError, json.JSONDecodeError):
                return 0.0
        return 0.0

    def should_run(self, charging: bool,
                   now: Optional[float] = None) -> bool:
        now = now if now is not None else self._now()
        if not charging:
            return False
        if not _is_night(time.localtime(now).tm_hour):
            return False
        return (now - self.last_night()) >= MIN_GAP_H * 3600.0

    # -- the night ------------------------------------------------------------

    def run(self, ring, drift=None, privacy=None,
            sweeps: int = 3, reel_dir: Optional[Path] = None,
            now: Optional[float] = None) -> DreamReel:
        """One night: cycle → apply to the durable bias → stamp → reel."""
        now = now if now is not None else self._now()
        cycle = REMCycle(ring, drift=drift, privacy=privacy,
                         seed=int(now // 86400), now_fn=lambda: now)
        reel = cycle.run(sweeps=sweeps)

        bias = RetrievalBias.load(self.vault_dir)
        reel.apply_to(bias)
        bias.save(self.vault_dir)

        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._stamp_path.write_text(json.dumps(
            {"ts": now, "dreams": len(reel.scenes)}))

        if reel_dir is not None and reel.scenes:
            render_reel(reel, reel_dir)
        return reel

    def maybe_run(self, charging: bool, ring, drift=None, privacy=None,
                  reel_dir: Optional[Path] = None,
                  now: Optional[float] = None) -> Optional[DreamReel]:
        if not self.should_run(charging, now=now):
            return None
        return self.run(ring, drift=drift, privacy=privacy,
                        reel_dir=reel_dir, now=now)
