"""user_model.py — the Juno learns you.

A light, private profile the Juno builds as you go, so it can adapt: what you
talk about (topics you return to), who you talk with, what you've told it to
remember, and what to call you. It's the difference between an assistant that
resets every session and one that already knows you.

Everything is learned on-device from lines you've already chosen to keep (the
conversation ledger) and from what you explicitly tell it ("call me Sam", "I
prefer aisle seats"). Only short keywords and preferences are stored — never raw
audio, never other people's words as *your* interests. Persisted as a small JSON
next to the vault when a path is given; in-memory otherwise. The caller gates
learning behind the Privacy Veil, exactly like the ledger.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# words that never count as an "interest"
_STOP = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "at",
    "is", "it", "that", "this", "with", "you", "i", "we", "they", "he", "she",
    "did", "say", "said", "about", "what", "was", "were", "me", "my", "your",
    "do", "does", "have", "has", "had", "so", "if", "then", "there", "here",
    "be", "are", "am", "as", "by", "from", "up", "out", "not", "no", "yes",
    "want", "need", "get", "got", "going", "just", "like", "one", "will",
    "can", "would", "could", "should", "think", "know", "really", "gonna",
    "let", "make", "made", "them", "our", "his", "her", "who", "how", "why",
})

_TOKEN = re.compile(r"[a-z][a-z'\-]{2,}")

# explicit teach cues
# deliberately explicit — "I'm …" is too ambiguous to read as a name
_NAME_RE = re.compile(r"\b(?:call me|my name is|name'?s)\s+([A-Za-z][\w'\-]{1,30})\b",
                      re.IGNORECASE)
_PREF_RE = re.compile(
    r"\b(?:i (?:prefer|like|love|always|usually|hate|avoid|can'?t stand)|"
    r"remember that i|remember i|note that i|for the record,? i)\b\s*(.+)",
    re.IGNORECASE)
# a name we should never accept as *the wearer's* name (pronouns / fillers)
_NOT_A_NAME = frozenset({"sorry", "not", "sure", "here", "good", "fine", "okay",
                         "ok", "just", "so", "really", "still", "afraid", "glad"})


@dataclass
class UserSnapshot:
    name: str
    interests: list[str]
    people: list[str]
    preferences: list[str]
    observations: int

    def to_dict(self) -> dict:
        return {"name": self.name, "interests": self.interests,
                "people": self.people, "preferences": self.preferences,
                "observations": self.observations}


class UserModel:
    """A small, growing picture of the wearer. Passive `observe`/`note_person`
    build it from the day; `learn` takes an explicit instruction."""

    def __init__(self, path: Optional[str] = None, *, max_topics: int = 300):
        self.path = path
        self.max_topics = max_topics
        self.name: str = ""
        self._topics: dict[str, int] = {}
        self._people: dict[str, int] = {}
        self._prefs: list[str] = []
        self._count: int = 0
        self._load()

    # -- passive learning ------------------------------------------------

    def observe(self, text: str, speaker: str = "") -> None:
        """Learn from a line the *wearer* said — the topics they return to. Lines
        from others don't shape your interests (only `note_person` does)."""
        if speaker and speaker.strip().lower() not in ("", "me"):
            return
        got = False
        for w in _TOKEN.findall((text or "").lower()):
            if w in _STOP:
                continue
            self._topics[w] = self._topics.get(w, 0) + 1
            got = True
        if got:
            self._count += 1
            self._prune()
            self._save()

    def note_person(self, name: str) -> None:
        """Record that you spoke with someone — builds 'who you talk to most.'"""
        n = (name or "").strip()
        if not n or n.lower() in ("me", "you"):
            return
        self._people[n] = self._people.get(n, 0) + 1
        self._save()

    # -- explicit teaching -----------------------------------------------

    def learn(self, text: str) -> Optional[dict]:
        """Take a direct instruction — "call me Sam", "I prefer aisle seats",
        "remember that I'm allergic to shellfish". Returns what was captured
        ({kind, value}) or None if it wasn't a teachable statement."""
        t = (text or "").strip()
        if not t:
            return None
        m = _NAME_RE.search(t)
        if m:
            name = m.group(1).strip()
            if name.lower() not in _NOT_A_NAME and not name.isdigit():
                self.name = name[:1].upper() + name[1:]
                self._save()
                return {"kind": "name", "value": self.name}
        m = _PREF_RE.search(t)
        if m:
            pref = _clean_pref(m.group(0))
            if pref and pref not in self._prefs:
                self._prefs.append(pref)
                self._prefs = self._prefs[-40:]     # keep the profile light
                self._save()
                return {"kind": "preference", "value": pref}
        return None

    # -- read the profile ------------------------------------------------

    def address(self) -> str:
        """What to call the wearer, or '' if we don't know yet."""
        return self.name

    def interests(self, n: int = 5) -> list[str]:
        return [w for w, _ in sorted(self._topics.items(),
                                     key=lambda kv: (-kv[1], kv[0]))[:max(0, n)]]

    def top_people(self, n: int = 5) -> list[str]:
        return [w for w, _ in sorted(self._people.items(),
                                     key=lambda kv: (-kv[1], kv[0]))[:max(0, n)]]

    def preferences(self) -> list[str]:
        return list(self._prefs)

    def snapshot(self, n: int = 5) -> UserSnapshot:
        return UserSnapshot(self.name, self.interests(n), self.top_people(n),
                            list(self._prefs), self._count)

    # -- persistence -----------------------------------------------------

    def _prune(self) -> None:
        if len(self._topics) <= self.max_topics:
            return
        keep = sorted(self._topics.items(), key=lambda kv: -kv[1])[: self.max_topics]
        self._topics = dict(keep)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"name": self.name, "topics": self._topics,
                           "people": self._people, "prefs": self._prefs,
                           "count": self._count}, f)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                d = json.load(f)
            self.name = d.get("name", "") or ""
            self._topics = {str(k): int(v) for k, v in (d.get("topics") or {}).items()}
            self._people = {str(k): int(v) for k, v in (d.get("people") or {}).items()}
            self._prefs = [str(x) for x in (d.get("prefs") or [])]
            self._count = int(d.get("count", 0) or 0)
        except Exception:
            pass


def _clean_pref(phrase: str) -> str:
    """Normalize a captured preference to a compact first-person line."""
    p = re.sub(r"^\s*(?:remember that|remember|note that|for the record,?)\s+",
               "", (phrase or "").strip(), flags=re.IGNORECASE)
    p = p.strip(" .,;:—-")
    if p and not p.lower().startswith("i "):
        p = "I " + p if not p.lower().startswith("i'") else p
    return p[:120]
