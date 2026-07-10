"""orchestrator/commands.py — "Hey Juno, *do* something."

Beyond asking questions, Juno runs the device. This is the grammar that turns
a spoken line into a device Command — focus, incognito, captions, proactive
alerts, rewind, sync, reminders. Anything that isn't a command falls through to
the knowledge/conversation router (voice.parse_intent), so "turn on focus" acts
and "what did Marcus need?" answers.

Pure and deterministic; the mic + ASR that produce the text are the device seam.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .voice import strip_wake

_OFF = ("off", "stop", "end", "disable", "exit", "cancel", "pause", "hide", "quiet")


@dataclass
class Command:
    kind: str                       # focus|incognito|captions|proactive|rewind|sync|remind|saga
    args: dict = field(default_factory=dict)


def _is_off(t: str) -> bool:
    return any(re.search(rf"\b{w}\b", t) for w in _OFF)


def parse_command(text: str):
    """Return a Command for a device instruction, or None if it isn't one."""
    t = strip_wake(text).lower().strip().rstrip(" ?.!")
    if not t:
        return None

    # focus mode
    if re.search(r"\bfocus(\s+mode)?\b", t) or "focusing" in t:
        return Command("focus", {"on": not _is_off(t)})

    # incognito / off the record
    if "incognito" in t or "off the record" in t or "go dark" in t:
        return Command("incognito", {"on": not _is_off(t)})

    # live captions
    if "caption" in t or "subtitle" in t:
        return Command("captions", {"on": not _is_off(t)})

    # proactive alerts ("let me know / keep watch / listen for me")
    if "proactive" in t or "keep watch" in t or ("alert" in t and ("on" in t or _is_off(t))):
        return Command("proactive", {"on": not _is_off(t)})

    # cloud tier
    if re.search(r"\bcloud\b", t):
        return Command("cloud", {"on": not _is_off(t)})

    # rewind / scrub the day
    if "rewind" in t or "scrub" in t or "replay my day" in t:
        return Command("rewind", {})

    # saga / progress
    if re.search(r"\bmy (rank|level|saga|badges|progress)\b", t) or "level am i" in t:
        return Command("saga", {})

    # sync a source
    m = re.search(r"\bsync\s+(?:my\s+)?(calendar|contacts|reminders)\b", t)
    if m:
        return Command("sync", {"what": m.group(1)})

    # remind me to … / add an event / schedule …
    m = re.match(r"(?:remind me to|add (?:an?\s+)?(?:event|reminder)(?:\s+to)?|schedule)\s+(.+)", t)
    if m:
        return Command("remind", {"title": m.group(1).strip()})

    return None
