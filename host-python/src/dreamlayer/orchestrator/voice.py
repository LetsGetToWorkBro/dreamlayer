"""orchestrator/voice.py — "Hey DreamLayer" intent routing.

Hands-free is the whole point of glasses, so this turns a spoken line into a
structured intent the orchestrator can act on. The microphone + speech-to-text
is a device seam (ASR isn't done here); this layer takes the *transcribed
text* and figures out what you meant:

    "Hey DreamLayer, what did Marcus need?"   → recall(query)
    "where did I leave my bike?"              → locate(subject="bike")
    "reply to Priya saying on my way"         → reply(to="Priya", text="on my way")
    "brief me" / "what's my day"              → brief
    "what did I miss?"                        → missed
    anything else                             → ask(query)

Pure and deterministic, so the grammar is fully unit-tested; the actual
speech capture and wake-word spotting live on the device.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

WAKE = ("hey dreamlayer", "ok dreamlayer", "dreamlayer")


@dataclass
class Intent:
    kind: str                       # recall|locate|reply|brief|missed|ask
    args: dict = field(default_factory=dict)


def strip_wake(text: str) -> str:
    """Drop a leading wake phrase (and stray punctuation) if present."""
    t = (text or "").strip()
    low = t.lower()
    for w in WAKE:
        if low.startswith(w):
            t = t[len(w):]
            break
    return t.lstrip(" ,.!—-").strip()


def parse_intent(text: str) -> Intent:
    raw = strip_wake(text)
    r = raw.strip().rstrip("?.!")            # original case, for captured content
    t = r.lower()                            # for keyword matching
    if not t:
        return Intent("ask", {"query": ""})

    # reply to <who> [with|saying] <text> — capture from the original casing
    m = re.match(r"(?:reply|respond|text|message)\s+(?:to\s+)?(\w[\w'.-]*)"
                 r"(?:[,:]?\s+(?:with|saying|that)\s+(.*))?$", r, re.IGNORECASE)
    if m:
        return Intent("reply", {"to": m.group(1), "text": (m.group(2) or "").strip()})

    # where's my <thing> / where did I leave <thing>
    m = re.match(r"(?:where'?s|where is|where did i (?:leave|put))\s+(?:my\s+|the\s+)?(.+)$",
                 r, re.IGNORECASE)
    if m:
        return Intent("locate", {"subject": m.group(1).strip()})

    # what did/does <who> need/want/say/owe → recall (send the whole phrasing)
    if re.match(r"what (?:did|does|is|are)\s+\w+.*(need|want|say|said|owe|owes)", t):
        return Intent("recall", {"query": raw.strip()})

    if "what did i miss" in t or "anything new" in t or "what's new" in t:
        return Intent("missed", {})
    if "brief" in t or t in ("my day", "what's my day", "whats my day"):
        return Intent("brief", {})

    return Intent("ask", {"query": raw.strip()})
