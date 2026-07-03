"""hud/audio.py — Oracle's earcons: the short sounds the glasses play, varied.

Cards carry an `earcon` id (e.g. "hark" for the "Listen!" tap, "wake" for a
greeting). Each id maps to a **family** of clips — Hey 1/2, Listen 1/2, Look
1/2, Watch-out 1/2 — so the wearer doesn't hear the exact same sound every time.
`pick_variant()` rotates without repeating the last one.

The runtime plays the actual audio through the glasses' speaker; this module is
the single source of truth for the ids, the families, and for resolving the
clip files you drop on disk. Drop your files in `<dir>/sounds/`, named after the
variant (e.g. `sounds/hey1.mp3`, `sounds/listen2.wav`). Anything missing simply
isn't in the rotation — a family with no files falls back to a built-in tone.
"""
from __future__ import annotations

import random
from pathlib import Path

# earcon id -> what it's for
EARCONS = {
    "wake":        "Oracle woke / a greeting — the 'Hey' family",
    "hark":        "Listen! — Oracle has something for you",
    "hark_urgent": "Watch out — an urgent heads-up",
    "look":        "Look at this — a thing worth your eyes",
    "chime":       "a neutral confirmation sound effect",
}

# earcon id -> the family of variant basenames (rotated at play time)
FAMILIES = {
    "wake":        ["hey1", "hey2"],
    "hark":        ["listen1", "listen2"],
    "hark_urgent": ["watchout1", "watchout2"],
    "look":        ["look1", "look2"],
    "chime":       ["sfx10", "sfx13"],
}

SOUNDS_DIR = "sounds"
_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".ogg")
_last: dict[str, str] = {}


def earcon_ids() -> list[str]:
    return list(EARCONS)


def is_earcon(name: str) -> bool:
    return name in EARCONS


def variants(name: str) -> list[str]:
    """The variant basenames for an earcon family."""
    return list(FAMILIES.get(name, []))


def pick_variant(name: str, rng=random) -> str | None:
    """Choose a variant for `name`, avoiding an immediate repeat. Returns the
    basename (e.g. 'listen2'), or None for an unknown earcon."""
    opts = FAMILIES.get(name)
    if not opts:
        return None
    if len(opts) == 1:
        _last[name] = opts[0]
        return opts[0]
    choice = rng.choice(opts)
    if choice == _last.get(name):
        choice = opts[(opts.index(choice) + 1) % len(opts)]
    _last[name] = choice
    return choice


def resolve_clip(base_dir: str | Path, variant: str) -> Path | None:
    """The file for a variant basename under `<base_dir>/sounds/`, or None."""
    d = Path(base_dir) / SOUNDS_DIR
    for ext in _EXTS:
        p = d / f"{variant}{ext}"
        if p.exists():
            return p
    return None


def present_variants(base_dir: str | Path, name: str) -> list[str]:
    """Which of an earcon's variants actually have a file on disk."""
    return [v for v in FAMILIES.get(name, []) if resolve_clip(base_dir, v)]
