"""Typed memory records where the Privacy Veil is a TYPE INVARIANT — a
MemoryEvent literally cannot be constructed with allowed=False.

ADD-alongside: new module. Uses pydantic when available (extras group
`structured`), else an equivalent @dataclass that raises the same way in
__post_init__. Either path guarantees a veiled write is impossible at
construction time.

    MemoryEvent(kind="Promise", summary="...", allowed=priv.allow_capture())
    # raises PrivacyViolation when allow_capture() is False
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.models_pydantic")

try:
    from pydantic import BaseModel  # type: ignore
    _HAS_PYDANTIC = True
except BaseException:  # ImportError, or a broken native install (pyo3 PanicException)
    _HAS_PYDANTIC = False


class PrivacyViolation(ValueError):
    """Raised when a memory record is constructed while capture is disallowed."""


if _HAS_PYDANTIC:
    class MemoryEvent(BaseModel):  # type: ignore[misc]
        kind: str = "Note"
        summary: str = ""
        confidence: float = 0.5
        allowed: bool = True

        def __init__(self, **data):
            # Enforce the veil BEFORE pydantic validation so PrivacyViolation
            # propagates directly (pydantic would otherwise wrap it in a
            # ValidationError), matching the dataclass fallback's behaviour.
            if data.get("allowed", True) is False:
                raise PrivacyViolation("memory write refused: capture not allowed")
            super().__init__(**data)
else:
    from dataclasses import dataclass

    @dataclass
    class MemoryEvent:  # type: ignore[no-redef]
        kind: str = "Note"
        summary: str = ""
        confidence: float = 0.5
        allowed: bool = True

        def __post_init__(self):
            if self.allowed is False:
                raise PrivacyViolation("memory write refused: capture not allowed")


available = _HAS_PYDANTIC
