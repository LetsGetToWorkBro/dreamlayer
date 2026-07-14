"""ember/engram.py — the record of a moment being tended.

An Engram is deliberately small: a cue (which prompts and never answers), the
answer it guards, an optional place gate, the scheduler state, and provenance
back to the warm store so the burn can be real (ceremony.py purges the source
row through the Retriever, ANN index included).

Naming note: cognitive science uses "engram" for the physical trace a memory
leaves in a brain. That is exactly the ambition here — the row in this store
is scaffolding around the trace in *your* head, and the row's life ends
(burned=True) when the trace no longer needs it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

from .scheduler import EngramState


@dataclass(frozen=True)
class Engram:
    """One kept moment and the state of its consolidation into the wearer."""
    id: int
    moment_key: str            # rem.bias.event_key of the source moment
    cue: str                   # what the glow asks — never the answer
    answer: str                # what the wearer is learning to retrieve
    state: EngramState
    kept_at: float             # epoch seconds of the tending choice
    place_signature: str = ""  # "" = fires anywhere; else only at this place
    source_memory_id: int = 0  # warm-store row the burn will purge (0 = none)
    burned: bool = False       # the raw trace is gone; only the cue remains
    burned_at: float = 0.0
    meta: dict = field(default_factory=dict)

    def with_state(self, state: EngramState) -> "Engram":
        return replace(self, state=state)

    # -- serialization (WeatherLedger convention: dict round-trip) ----------

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "moment_key": self.moment_key,
            "cue": self.cue,
            "answer": self.answer,
            "kept_at": self.kept_at,
            "place_signature": self.place_signature,
            "source_memory_id": self.source_memory_id,
            "burned": self.burned,
            "burned_at": self.burned_at,
            "meta": self.meta,
            "stability": self.state.stability,
            "difficulty": self.state.difficulty,
            "due_ts": self.state.due_ts,
            "reps": self.state.reps,
            "lapses": self.state.lapses,
            "last_review_ts": self.state.last_review_ts,
            "graduated": self.state.graduated,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Engram":
        meta = row.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        return cls(
            id=int(row["id"]),
            moment_key=row["moment_key"],
            cue=row["cue"],
            answer=row.get("answer", "") or "",
            kept_at=float(row["kept_at"]),
            place_signature=row.get("place_signature", "") or "",
            source_memory_id=int(row.get("source_memory_id") or 0),
            burned=bool(row.get("burned")),
            burned_at=float(row.get("burned_at") or 0.0),
            meta=meta,
            state=EngramState(
                stability=float(row["stability"]),
                difficulty=float(row["difficulty"]),
                due_ts=float(row["due_ts"]),
                reps=int(row.get("reps") or 0),
                lapses=int(row.get("lapses") or 0),
                last_review_ts=float(row.get("last_review_ts") or 0.0),
                graduated=bool(row.get("graduated")),
            ),
        )


@dataclass(frozen=True)
class TendingCandidate:
    """A moment the night offers over coffee: keep it, or let it fade.
    Candidates are pure suggestions — nothing becomes an Engram without the
    wearer's explicit keep (nothing is saved until you say so)."""
    id: int
    kind: str
    summary: str
    cue: str
    salience: float
    place_signature: str = ""
    source_memory_id: int = 0
    night_seed: int = 0
