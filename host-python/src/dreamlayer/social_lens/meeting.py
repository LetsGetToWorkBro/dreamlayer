"""social_lens/meeting.py — keep track of what happens in a meeting.

Start a meeting and Juno holds the thread: who's here (the people you've met),
the notes as they land, and — the point — the action items and commitments
pulled out of them ("I'll send the deck Friday", "Marcus will follow up"). No
cloud: it's your own words, on device.

`MeetingLog` is pure + stdlib (a JSON file), so it tests fully offline. Action
extraction is deterministic here; a sharper NER (GLiNER) can slot behind
`extract_actions` later without changing the store.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# "I'll email Priya Friday", "we'll ship Tuesday", "let's circle back",
# "Marcus will follow up", "TODO: book the room", "action: sign the lease".
_ACTION = re.compile(
    r"\b("
    r"(?:i['’]?ll|i will|we['’]?ll|we will|let['’]?s)\s+.+?"
    r"|[A-Z][a-zà-ÿ'’-]+\s+(?:will|is going to|to)\s+.+?"
    r"|(?:todo|to-do|action item|action|next step)s?\s*[:\-]\s*.+?"
    r")(?:[.!?]|$)", re.I)

# a due-date phrase, kept alongside the action so a commitment carries its when
_WHEN = re.compile(
    r"\b(by\s+\w+|today|tonight|tomorrow|this week|next week|"
    r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|"
    r"sat(?:urday)?|sun(?:day)?|\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", re.I)


def extract_actions(text: str) -> list[dict]:
    """Pull action items / commitments out of a line of meeting talk. Each is
    {text, when} where `when` is a due phrase if one is present, else ""."""
    out: list[dict] = []
    for m in _ACTION.finditer(text or ""):
        phrase = " ".join(m.group(1).split()).strip(" .!?,")
        if len(phrase) < 4:
            continue
        wm = _WHEN.search(phrase)
        out.append({"text": phrase[:200], "when": (wm.group(1) if wm else "")})
    return out


class MeetingLog:
    """A tiny append-only meeting store backed by one JSON file."""

    def __init__(self, path, now_fn=None, ner=None):
        self.path = Path(path)
        import time
        self._now = now_fn or time.time
        # optional sharper extractor (GLiNER); when present its commitments are
        # merged on top of the deterministic ones. `ner.extract(text)->[{text,
        # when, who}]`. None → deterministic only.
        self._ner = ner

    # -- persistence -------------------------------------------------------
    def _load(self) -> list:
        try:
            data = json.loads(self.path.read_text()) if self.path.exists() else []
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self, data: list) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False))
        except OSError:
            pass

    # -- lifecycle ---------------------------------------------------------
    def current(self) -> Optional[dict]:
        for m in reversed(self._load()):
            if not m.get("ended"):
                return m
        return None

    def start(self, title: str = "", attendees=()) -> dict:
        data = self._load()
        for m in data:                                 # close any dangling meeting
            if not m.get("ended"):
                m["ended"] = self._now()
        meeting = {
            "id": int(self._now() * 1000),
            "title": (title or "").strip()[:120],
            "started": self._now(), "ended": 0.0,
            "attendees": [str(a).strip() for a in (attendees or []) if str(a).strip()],
            "notes": [], "actions": [], "decisions": [],
        }
        data.append(meeting)
        self._save(data)
        return meeting

    def note(self, text: str) -> Optional[dict]:
        """Append a note to the live meeting and harvest any actions from it.
        Returns the updated meeting, or None if no meeting is running."""
        text = (text or "").strip()
        if not text:
            return self.current()
        data = self._load()
        live = next((m for m in reversed(data) if not m.get("ended")), None)
        if live is None:
            return None
        live["notes"].append({"text": text[:500], "ts": self._now()})
        actions = list(extract_actions(text))
        if self._ner is not None:                      # GLiNER catches what regex can't
            try:
                for e in self._ner.extract(text) or []:
                    actions.append({"text": str(e.get("text", ""))[:200],
                                    "when": str(e.get("when", ""))})
            except Exception:                          # noqa: BLE001 — never break a note
                pass
        for a in actions:
            if a.get("text") and a not in live["actions"]:
                live["actions"].append(a)
        # "we decided to …" / "decision: …" is a decision, not a to-do
        if re.search(r"\b(we decided|decision\s*[:\-]|agreed to)\b", text, re.I):
            live["decisions"].append(text[:200])
        self._save(data)
        return live

    def add_attendee(self, name: str) -> Optional[dict]:
        name = (name or "").strip()
        data = self._load()
        live = next((m for m in reversed(data) if not m.get("ended")), None)
        if live is None or not name:
            return live
        if name not in live["attendees"]:
            live["attendees"].append(name)
            self._save(data)
        return live

    def end(self) -> Optional[dict]:
        data = self._load()
        live = next((m for m in reversed(data) if not m.get("ended")), None)
        if live is None:
            return None
        live["ended"] = self._now()
        self._save(data)
        return live

    def all(self, limit: int = 50) -> list:
        return list(reversed(self._load()))[:max(0, limit)]
