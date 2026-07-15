"""rem/bias.py — the RetrievalBias store: what the night decided.

A small, durable map from event identity to a bounded rank delta in
[-BIAS_MAX, +BIAS_MAX]. Written by the REM cycle, read by anything that
ranks memories (retrieval scoring, the Horizon composer's luma boost).

Deliberately dumb storage: one JSON file in the vault directory, keys
are content hashes (kind + normalized summary), values are floats.
apply() merges a night's deltas; decay() fades old opinions so a single
vivid night doesn't dominate a month.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

BIAS_MAX = 0.5
DECAY = 0.5          # each new night halves the previous nights' residue
FILENAME = "rem_bias.json"


def event_key(kind: str, summary: str) -> str:
    """Stable identity for an event across sessions: kind + normalized
    summary. Timestamps deliberately excluded — 'call Maya' tonight and
    'call Maya' next week are the same memory to the dreamer."""
    norm = re.sub(r"\s+", " ", (summary or "").strip().lower())
    return hashlib.sha256(f"{kind}|{norm}".encode("utf-8")).hexdigest()[:16]


class RetrievalBias:
    def __init__(self, values: dict[str, float] | None = None) -> None:
        self._v: dict[str, float] = dict(values or {})

    # -- reads -----------------------------------------------------------

    def get(self, key: str) -> float:
        return self._v.get(key, 0.0)

    def boost_for(self, kind: str, summary: str) -> float:
        return self.get(event_key(kind, summary))

    def __len__(self) -> int:
        return len(self._v)

    def as_dict(self) -> dict[str, float]:
        return dict(self._v)

    # -- writes ----------------------------------------------------------

    def apply(self, deltas: dict[str, float]) -> None:
        """Merge one night's deltas, clamped to the bias envelope."""
        for key, delta in deltas.items():
            merged = self._v.get(key, 0.0) + float(delta)
            self._v[key] = max(-BIAS_MAX, min(BIAS_MAX, merged))

    def decay(self) -> None:
        """Fade all opinions; forget the ones that fade to noise."""
        faded = {k: v * DECAY for k, v in self._v.items()}
        self._v = {k: v for k, v in faded.items() if abs(v) > 0.01}

    def remove(self, key: str) -> bool:
        """Drop one opinion by key. Returns whether anything was removed."""
        return self._v.pop(key, None) is not None

    def discard(self, kind: str, summary: str) -> bool:
        """Drop the opinion for a memory by its content identity — the erase
        hook for "forget that". Without this a forgotten memory left a durable
        content-hash fingerprint plus a rank-ghost that silently re-attached its
        old consolidation priority on re-ingest (audit 2026-07-14)."""
        return self.remove(event_key(kind, summary))

    def clear(self) -> None:
        """Forget every opinion — the erase-everything hook."""
        self._v.clear()

    # -- persistence -------------------------------------------------------

    def save(self, directory: Path | str) -> Path:
        # tmp + os.replace: a crash mid-write must never leave a torn
        # rem_bias.json — load() would raise on it forever after, killing
        # every future night (audit 2026-07-14: non-transactional
        # consolidation).
        path = Path(directory) / FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._v, sort_keys=True, indent=1))
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, directory: Path | str) -> "RetrievalBias":
        path = Path(directory) / FILENAME
        if not path.exists():
            return cls()
        return cls(json.loads(path.read_text()))
