"""LatentSpatialMemory-style anchoring — recall triggered by *where you are*,
not only when/keyword.

ADD-alongside: brand-new file (no spatial anchor existed). No hard dep (the
Microsoft repo is research code); this is a self-contained place→memory index
with a clean interface a learned latent model can back later.
"""
from __future__ import annotations


class SpatialMemory:
    available = True  # pure-Python, always available

    def __init__(self):
        self._by_place: dict[str, list[dict]] = {}

    def anchor(self, place_id: str, memory: dict) -> None:
        """Attach a memory record to a place signature."""
        self._by_place.setdefault(place_id, []).append(memory)

    def recall(self, place_id: str, limit: int = 5) -> list[dict]:
        """Memories anchored to the place you're standing in (most-recent first)."""
        return self._by_place.get(place_id, [])[-limit:][::-1]

    def places(self) -> list[str]:
        return list(self._by_place.keys())
