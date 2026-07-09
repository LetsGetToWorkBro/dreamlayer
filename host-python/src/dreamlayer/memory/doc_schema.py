"""Typed multimodal memory document (docarray) — one serializable record with
text + optional embedding + place + timestamp + thumbnail ref.

ADD-alongside: new sibling. Lazy-imports docarray (extras group `memory`);
when absent it exposes an equivalent plain @dataclass with the same fields and
`.to_row()`, so callers get a stable schema either way.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List

try:  # optional dep — extras group `memory`
    from docarray import BaseDoc  # type: ignore
    from docarray.typing import NdArray  # type: ignore
    _HAS_DOCARRAY = True
except ImportError:
    _HAS_DOCARRAY = False


if _HAS_DOCARRAY:
    class MemoryDoc(BaseDoc):  # type: ignore[misc]
        kind: str = "Note"
        summary: str = ""
        embedding: Optional[NdArray] = None  # type: ignore[valid-type]
        place_id: Optional[str] = None
        created_at: str = ""
        ts: int = 0
        thumb_ref: Optional[str] = None

        def to_row(self) -> dict:
            return {
                "kind": self.kind, "summary": self.summary,
                "embedding": (list(self.embedding) if self.embedding is not None else None),
                "place_id": self.place_id, "created_at": self.created_at,
                "ts": self.ts, "thumb_ref": self.thumb_ref,
            }
else:
    @dataclass
    class MemoryDoc:  # type: ignore[no-redef]
        kind: str = "Note"
        summary: str = ""
        embedding: Optional[List[float]] = None
        place_id: Optional[str] = None
        created_at: str = ""
        ts: int = 0
        thumb_ref: Optional[str] = None

        def to_row(self) -> dict:
            return asdict(self)


available = _HAS_DOCARRAY
