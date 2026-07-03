"""conversation.py — the spoken-word ledger behind live captions and recall.

The glasses (or phone) turn speech into text; that transcription is a device
seam. What lives here is everything the wearer can *do* with those lines once
they exist:

  • live captions — the last few utterances, ready for the HUD;
  • recall — "what did they say about the lease?" across the day;
  • rewind — a chronological digest of the day, grouped by hour;
  • dossier — who is this, when did we last talk, what's still open.

Only short semantic lines are kept, in a bounded ring — never raw audio. The
Privacy Veil gates ingestion at the orchestrator layer, so nothing here records
while capture is paused or you're incognito.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from collections import deque
from typing import Optional


# common words we don't treat as a recall "topic"
_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "at",
    "is", "it", "that", "this", "with", "you", "i", "we", "they", "he", "she",
    "did", "say", "said", "about", "what", "was", "were", "me", "my", "your",
    "do", "does", "have", "has", "had", "so", "if", "then", "there", "here",
    "be", "are", "am", "as", "by", "from", "up", "out", "not", "no", "yes",
}


@dataclass
class Utterance:
    ts: float
    speaker: str          # "" or "me" for the wearer; a name for others
    text: str

    def is_mine(self) -> bool:
        return self.speaker == "" or self.speaker.lower() == "me"


def _keywords(topic: str) -> list[str]:
    return [w for w in _norm(topic).split() if w and w not in _STOP]


def _norm(s: str) -> str:
    return "".join(c.lower() if (c.isalnum() or c.isspace()) else " " for c in s)


class ConversationLedger:
    """A bounded, newest-last log of transcribed utterances."""

    def __init__(self, capacity: int = 2000):
        self._log: deque[Utterance] = deque(maxlen=max(1, capacity))

    def add(self, text: str, speaker: str = "", ts: Optional[float] = None) -> Optional[Utterance]:
        text = (text or "").strip()
        if not text:
            return None
        u = Utterance(ts=ts if ts is not None else time.time(),
                      speaker=(speaker or "").strip(), text=text)
        self._log.append(u)
        return u

    def __len__(self) -> int:
        return len(self._log)

    # -- live captions ---------------------------------------------------

    def captions(self, n: int = 6) -> list[Utterance]:
        """The last `n` utterances, oldest→newest, for the caption strip."""
        if n <= 0:
            return []
        return list(self._log)[-n:]

    def last_other_speaker(self) -> str:
        """The most recent person (not the wearer) who spoke — i.e. who you're
        talking to right now. '' if only you have spoken."""
        for u in reversed(self._log):
            if not u.is_mine():
                return u.speaker
        return ""

    # -- recall ----------------------------------------------------------

    def recall(self, topic: str, person: Optional[str] = None,
               limit: int = 8) -> list[Utterance]:
        """Lines matching a topic (any keyword), newest first. Optionally scoped
        to what one person said."""
        kws = _keywords(topic)
        person_l = person.lower().strip() if person else None
        out: list[Utterance] = []
        for u in reversed(self._log):
            if person_l and u.speaker.lower() != person_l:
                continue
            if kws:
                hay = _norm(u.text)
                if not any(k in hay for k in kws):
                    continue
            out.append(u)
            if len(out) >= limit:
                break
        return out

    # -- rewind my day ---------------------------------------------------

    def timeline(self, day_start: float, day_end: Optional[float] = None,
                 per_hour: int = 3) -> list[dict]:
        """A digest of the day grouped into hour blocks. Each block carries a
        label ("2 PM"), the people heard, and up to `per_hour` sample lines."""
        end = day_end if day_end is not None else day_start + 86400
        blocks: dict[int, list[Utterance]] = {}
        for u in self._log:
            if not (day_start <= u.ts < end):
                continue
            hr = int((u.ts - day_start) // 3600)
            blocks.setdefault(hr, []).append(u)
        out: list[dict] = []
        for hr in sorted(blocks):
            items = blocks[hr]
            people = []
            for u in items:
                who = u.speaker or "You"
                if who not in people:
                    people.append(who)
            out.append({
                "hour": hr,
                "label": _hour_label(day_start + hr * 3600),
                "count": len(items),
                "people": people,
                "lines": [{"speaker": u.speaker or "You", "text": u.text}
                          for u in items[:per_hour]],
            })
        return out

    # -- person dossier --------------------------------------------------

    def dossier(self, person: str, now: Optional[float] = None,
                recent: int = 3) -> dict:
        """What we know from talking with `person`: when last heard, how many
        exchanges, the topics that came up, and their most recent lines."""
        now = now if now is not None else time.time()
        person_l = person.lower().strip()
        theirs = [u for u in self._log if u.speaker.lower() == person_l]
        if not theirs:
            return {"person": person, "known": False}
        last = theirs[-1]
        freq: dict[str, int] = {}
        for u in theirs:
            for w in _keywords(u.text):
                freq[w] = freq.get(w, 0) + 1
        topics = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:5]]
        return {
            "person": person,
            "known": True,
            "exchanges": len(theirs),
            "last_seen_ago": _ago(now - last.ts),
            "last_line": last.text,
            "topics": topics,
            "recent": [u.text for u in theirs[-recent:]],
        }


# --- commitment capture: turn "I'll send you the lease by Friday" into a task -
# A promise the *wearer* makes to whoever they're talking to. Deliberately
# conservative: it only fires on a first-person promise cue, so passing remarks
# don't become tasks. The mic + ASR that produce the text are the device seam.

_PROMISE_RE = re.compile(
    r"\b(?:i(?:'| a)?ll|i will|i can|i promise to|let me|i'll go)\b",
    re.IGNORECASE)
_DUE_RE = re.compile(
    r"\b(?:by|before|on|this|next|tomorrow|tonight|today|end of)\b[^.,;]*", re.IGNORECASE)
_DUE_WORDS = ("tomorrow", "tonight", "today", "monday", "tuesday", "wednesday",
              "thursday", "friday", "saturday", "sunday", "week", "weekend",
              "morning", "afternoon", "evening", "noon", "eod")


def parse_commitment(text: str) -> Optional[dict]:
    """If `text` is a first-person promise, pull out {task, due}. Else None.

    'I'll send you the lease by Friday' → {task: 'send you the lease by
    Friday', due: 'by Friday'}. Pure and synthetic-testable — no model needed;
    a richer extractor can replace it behind the same shape.
    """
    t = (text or "").strip()
    m = _PROMISE_RE.search(t)
    if not m:
        return None
    task = t[m.end():].strip(" ,.;:—-")
    if len(task) < 3:
        return None
    due = ""
    dm = _DUE_RE.search(task)
    if dm and any(w in dm.group(0).lower() for w in _DUE_WORDS):
        due = dm.group(0).strip(" ,.;:")
    return {"task": task, "due": due}


def _hour_label(ts: float) -> str:
    lt = time.localtime(ts)
    h = lt.tm_hour
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12} {ampm}"


def _ago(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return "just now"
    m = s // 60
    if m < 60:
        return f"{m} min ago"
    h = m // 60
    if h < 24:
        return f"{h} hr ago"
    d = h // 24
    return f"{d} day{'s' if d != 1 else ''} ago"
