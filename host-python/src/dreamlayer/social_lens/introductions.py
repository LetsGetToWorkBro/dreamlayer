"""social_lens/introductions.py — recognize an introduction and pull the name.

"This is Sarah", "meet Sarah from marketing", "her name is Sarah", "I'm Sarah" —
the moment someone is introduced (or introduces themselves) is the CONSENT moment
that lets the Social Lens remember them. Recognizing people you've met is the
product's point; this is the deterministic front door that enrolls them.

Pure/stdlib, so it runs everywhere with no optional deps. Returns
{"name": ..., "note": ...} or None. Conservative: it only fires on a clear
introduction cue followed by a name-shaped token, so ordinary speech doesn't
enroll a stranger by accident.
"""
from __future__ import annotations

import re
from typing import Optional

# The name that follows a cue: 1–3 CAPITALISED words (accents allowed:
# "Tomás", "Renée", internal caps like "O'Neil"/"McDonald"). Case-SENSITIVE on
# purpose — the leading capital is what tells a name from an ordinary word, so
# the cue prefixes below scope their case-insensitivity with (?i:…) and never
# let re.I leak onto this class (which would match "from"/"me" as a name).
_NAME = r"([A-ZÀ-Ÿ][a-zà-ÿA-ZÀ-Ÿ'’-]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿA-ZÀ-Ÿ'’-]+){0,2})"

# Introduction cues. Each captures the name in group 1; a trailing "from/at/who/…"
# clause becomes the note. Ordered most-specific first.
_CUES = [
    re.compile(r"(?i:\b(?:this is|that['i]s|here['i]s))\s+(?i:my\s+\w+\s+)?" + _NAME),
    re.compile(r"(?i:\b(?:i'?d like you to meet|say hi to|say hello to|meet))\s+" + _NAME),
    re.compile(r"(?i:\b(?:his|her|their)\s+name['i]?s?\s+(?:is\s+)?)" + _NAME),
    re.compile(r"(?i:\bi(?:'?m| am))\s+" + _NAME),
    re.compile(r"(?i:\bmy\s+name['i]?s?\s+(?:is\s+)?)" + _NAME),
    re.compile(r"(?i:\b(?:remember|introduc\w+))\s+" + _NAME),
]

# A trailing context clause ("from marketing", "at Acme", "who I met at the con")
# → kept as the person's note.
_NOTE = re.compile(
    r"\b(from|at|who|works?\s+at|with)\b\s+(.+)$", re.I)

# Words that look name-shaped after a cue but are NOT a person (so "I'm sorry",
# "this is great" don't enroll "Sorry"/"Great").
_STOP = {
    "i", "a", "an", "the", "sorry", "here", "there", "good", "great", "fine",
    "okay", "ok", "done", "back", "home", "sure", "ready", "going", "glad",
    "happy", "afraid", "not", "just", "still", "now", "so", "really",
}


def parse_introduction(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if not t:
        return None
    for cue in _CUES:
        m = cue.search(t)
        if not m:
            continue
        name = " ".join(w for w in m.group(1).split())
        first = name.split()[0].lower() if name else ""
        if not first or first in _STOP:
            continue
        # note = whatever context trails the name in the sentence
        tail = t[m.end():]
        note = ""
        nm = _NOTE.search(tail)
        if nm:
            note = (nm.group(1) + " " + nm.group(2)).strip()[:120]
        return {"name": name, "note": note}
    return None
