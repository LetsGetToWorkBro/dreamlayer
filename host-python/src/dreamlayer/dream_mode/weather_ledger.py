"""dream_mode/weather_ledger.py — the room's memory of its own light.

Records the ambient palette weather (the exact colors MicReactor shipped
to the glasses) keyed by place signature and time, so Yesterlight can
replay a place as it actually was. Snapshots are tiny — four YCbCr slot
dicts plus an amplitude — sampled at most once per SNAPSHOT_EVERY_S, so
a full day is a few thousand rows.

Privacy contract: recording honors the same gate as capture — when the
Privacy Veil is up (allow_capture() False) nothing is written; replay of
already-lawfully-recorded weather remains available.
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SNAPSHOT_EVERY_S = 5.0
CAPACITY = 4096                 # ≈ 5.7 h of continuous ambience per place-day
NEAREST_TOLERANCE_S = 900.0     # a replay may sit ±15 min from the ask


@dataclass
class WeatherSnapshot:
    ts: float
    place: str
    colors: list          # the palette frame's colors payload, verbatim
    amplitude: float

    def to_row(self) -> dict:
        return {"ts": self.ts, "place": self.place,
                "colors": self.colors, "amp": self.amplitude}

    @staticmethod
    def from_row(row: dict) -> "WeatherSnapshot":
        return WeatherSnapshot(row["ts"], row["place"],
                               row["colors"], row.get("amp", 0.0))


class WeatherLedger:
    def __init__(self, privacy=None, capacity: int = CAPACITY,
                 now_fn=None) -> None:
        self._privacy = privacy
        self._now = now_fn or time.time
        self._buf: deque[WeatherSnapshot] = deque(maxlen=capacity)
        self._last_record = 0.0

    # -- recording ---------------------------------------------------------

    def record(self, place: Optional[str], palette_cmd: Optional[dict],
               amplitude: Optional[float] = None) -> bool:
        """Record one weather snapshot. Returns True if written."""
        if not place or not palette_cmd:
            return False
        if self._privacy is not None and not self._privacy.allow_capture():
            return False
        now = self._now()
        if now - self._last_record < SNAPSHOT_EVERY_S:
            return False
        colors = palette_cmd.get("colors")
        if not colors:
            return False
        self._buf.append(WeatherSnapshot(
            ts=now, place=place, colors=colors,
            amplitude=float(amplitude or 0.0)))
        self._last_record = now
        return True

    # -- queries -------------------------------------------------------------

    def nearest(self, place: str, target_ts: float,
                tolerance_s: float = NEAREST_TOLERANCE_S
                ) -> Optional[WeatherSnapshot]:
        """The snapshot closest to target_ts at this place, or None."""
        best: Optional[WeatherSnapshot] = None
        best_d = tolerance_s
        for snap in self._buf:
            if snap.place != place:
                continue
            d = abs(snap.ts - target_ts)
            if d <= best_d:
                best, best_d = snap, d
        return best

    def span(self, place: str) -> Optional[tuple[float, float]]:
        """(oldest_ts, newest_ts) recorded at this place, or None."""
        stamps = [s.ts for s in self._buf if s.place == place]
        if not stamps:
            return None
        return min(stamps), max(stamps)

    def __len__(self) -> int:
        return len(self._buf)

    # -- persistence (phone-local, explicit) ---------------------------------

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            for snap in self._buf:
                fh.write(json.dumps(snap.to_row(), sort_keys=True) + "\n")
        return path

    @classmethod
    def load(cls, path: Path | str, privacy=None,
             now_fn=None) -> "WeatherLedger":
        ledger = cls(privacy=privacy, now_fn=now_fn)
        path = Path(path)
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    ledger._buf.append(
                        WeatherSnapshot.from_row(json.loads(line)))
        return ledger
