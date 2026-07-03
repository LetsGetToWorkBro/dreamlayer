"""hud/audio.py — Oracle's earcons: the short sounds the glasses play.

Cards carry an `earcon` id (e.g. "hark" for the Navi-style "Listen!"); the
device runtime maps that id to an actual clip and plays it through the glasses'
speaker. This module is the single source of truth for the ids and for
resolving a **custom** clip you drop on disk — so the sound Oracle makes when it
needs your ear is yours to choose.

Drop your files in `<dir>/sounds/` named after the id, e.g. `sounds/hark.wav`
(or .mp3 / .m4a). `resolve_clip()` finds it; if none is present the runtime
falls back to a built-in tone, so nothing ever breaks for lack of a file.
"""
from __future__ import annotations

from pathlib import Path

# id -> what it's for (and the intended character of the sound)
EARCONS = {
    "wake":    "Oracle woke — a soft rising two-tone",
    "hark":    "Listen! — Oracle has something for you (the custom clip)",
    "success": "a light confirmation chime",
    "warn":    "a gentle caution tone",
}

SOUNDS_DIR = "sounds"
_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".ogg")


def earcon_ids() -> list[str]:
    return list(EARCONS)


def is_earcon(name: str) -> bool:
    return name in EARCONS


def resolve_clip(base_dir: str | Path, name: str) -> Path | None:
    """The custom clip for earcon `name` under `<base_dir>/sounds/`, or None."""
    if not is_earcon(name):
        return None
    d = Path(base_dir) / SOUNDS_DIR
    for ext in _EXTS:
        p = d / f"{name}{ext}"
        if p.exists():
            return p
    return None
