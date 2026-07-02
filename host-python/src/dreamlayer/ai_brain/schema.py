"""ai_brain/schema.py — the shape of an answer from any tier of the brain."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Answer:
    """What a brain returns. Always attributed to the tier it came from, so
    the HUD can show provenance and the Provenance Lens can trace it."""
    text: str
    sources: list[str] = field(default_factory=list)   # files/context used
    tier: str = ""                 # "device" | "laptop" | "cloud"
    confidence: float = 0.0

    def is_empty(self) -> bool:
        return not (self.text or "").strip()
