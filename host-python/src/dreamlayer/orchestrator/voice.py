"""orchestrator/voice.py — "Hey Oracle" wake + intent routing.

Hands-free is the whole point of glasses, so this turns a spoken line into a
structured intent the orchestrator can act on. The microphone + speech-to-text
is a device seam (ASR isn't done here); this layer takes the *transcribed
text*, strips the wake phrase (detect_wake), and figures out what you meant:

    "Hey Oracle, what did Marcus need?"       → recall(query)
    "where did I leave my bike?"              → locate(subject="bike")
    "reply to Priya saying on my way"         → reply(to="Priya", text="on my way")
    "remember Maya's into rock climbing"      → note_person(who="Maya", note="into rock climbing")
    "remember she works at Google"            → note_person(who=None, note="works at Google")
    "set a timer for five minutes"            → timer(seconds=300)
    "interval timer, 30 on, 15 off, 8 rounds" → interval(work=30, rest=15, rounds=8)
    "stop the timer"                          → timer_cancel
    "what time is it?" / "show a clock"       → clock(mode="time"|"show")
    "brief me" / "what's my day"              → brief
    "what did I miss?"                        → missed
    "what's the answer?"                      → scholar(mode="answer")
    "how do I fill this out to renew?"        → scholar(mode="form", purpose=...)
    "explain this" / "what does this mean?"   → scholar(mode="explain")
    anything else                             → ask(query)

Pure and deterministic, so the grammar is fully unit-tested; the actual
speech capture and wake-word spotting live on the device.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Oracle is DreamLayer's assistant. "Hey Oracle" is the primary wake phrase;
# the rest are graceful variants (and the old DreamLayer names, kept working).
ASSISTANT_NAME = "Oracle"
WAKE = ("hey oracle", "ok oracle", "okay oracle", "oracle",
        "hey dreamlayer", "ok dreamlayer", "dreamlayer")


@dataclass
class Intent:
    kind: str                       # recall|locate|reply|brief|missed|scholar|ask
    args: dict = field(default_factory=dict)


# -- native timers & clock: the everyday behaviors Oracle just builds --------

_WORD_NUM = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "fortyfive": 45, "fifty": 50, "sixty": 60, "ninety": 90,
}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted(_WORD_NUM, key=len, reverse=True)) + r")"
_UNIT_SEC = {"hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
             "minute": 60, "minutes": 60, "min": 60, "mins": 60,
             "second": 1, "seconds": 1, "sec": 1, "secs": 1}
_DUR_RE = re.compile(_NUM + r"\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b")
_ROUNDS_RE = re.compile(_NUM + r"\s*(rounds?|sets?|reps?|times|intervals?|cycles?)\b")


def _num(tok: str) -> float:
    return float(tok) if tok not in _WORD_NUM else float(_WORD_NUM[tok])


def _durations(t: str) -> list[float]:
    """Every duration in the line, in order, as seconds."""
    out = []
    for num, unit in _DUR_RE.findall(t):
        out.append(_num(num) * _UNIT_SEC[unit.rstrip("s") if unit.rstrip("s") in _UNIT_SEC else unit])
    return out


def _parse_timer_clock(t: str) -> "Intent | None":
    """Native timer / interval / clock intents, or None if the line isn't one.
    `t` is the lowercased, wake-stripped command."""
    has_timer_word = bool(re.search(r"\btimer\b|\binterval", t))
    # stop/cancel a running one — an explicit verb, or "timer off" adjacently
    # (so "15 seconds off" in an interval doesn't read as a cancel)
    if re.search(r"\b(cancel|stop|clear|dismiss|kill)\b.*\b(timer|intervals?|clock|countdown)\b", t) \
            or re.search(r"\b(timer|clock|countdown)s?\s+(off|stop)\b", t):
        return Intent("timer_cancel", {})
    # clock — "what time is it", "show a clock", "clock on the hud"
    if not has_timer_word:
        if re.search(r"\bwhat(?:'?s| is)?\s+the\s+time\b", t) or "what time is it" in t \
                or re.search(r"\btell me the time\b", t):
            return Intent("clock", {"mode": "time"})
        if re.search(r"\b(show|put|display|start)\b.*\bclock\b", t) \
                or re.search(r"\bclock\b.*\b(on|up|hud|please)\b", t) or t in ("clock", "a clock"):
            return Intent("clock", {"mode": "show"})
    durs = _durations(t)
    # interval — two phases (work/rest, on/off) or the word "interval"
    is_interval = "interval" in t or (
        len(durs) >= 2 and re.search(r"\b(on|off|work|working|rest|active|recover)\b", t))
    if is_interval and durs:
        work = durs[0]
        rest = durs[1] if len(durs) >= 2 else durs[0]
        rm = _ROUNDS_RE.search(t)
        rounds = int(_num(rm.group(1))) if rm else None
        return Intent("interval", {"work": work, "rest": rest, "rounds": rounds})
    # plain timer — "set a timer for X", "X minute timer", "count down X"
    wants_timer = has_timer_word or re.search(r"\bcount ?down\b", t) \
        or re.search(r"\bset (?:a |an )?(?:timer|alarm)\b", t)
    if wants_timer and durs:
        return Intent("timer", {"seconds": sum(durs)})
    return None


# -- "jot a note about a person" ---------------------------------------------

_REMEMBER_RE = re.compile(
    r"^(?:remember|note|jot down|make a note)(?:\s+that)?\s+(.+)$", re.I)
_WEARER_SUBJECT = re.compile(r"^(?:i|i'?m|im|my|me|myself)\b", re.I)
_PERSON_PRONOUN = re.compile(
    r"^(he|she|they|him|her|them|this\s+(?:person|guy|woman|man|lady|dude))\b(.*)$", re.I)
_NAME_LEAD = re.compile(r"^([A-Z][a-zA-Z.\-]*)(?:['’]s)?\s+(.+)$")
_NOT_A_NAME_WORD = {"the", "to", "that", "this", "it", "when", "where", "how",
                    "what", "there", "here", "and", "but"}


def _strip_copula(fact: str) -> str:
    """Drop a leading 'is/are/was/'s' so "is into climbing" reads as a note."""
    return re.sub(r"^(?:is|are|was|were|'?s)\s+", "", fact, flags=re.I).strip()


def _parse_person_note(r: str) -> "Intent | None":
    """"remember Maya's into rock climbing" / "note that Priya has two kids" /
    "remember she works at Google" → a note about a person. `who` is a name, or
    None to mean whoever you're looking at. Wearer statements ("remember I…")
    are left alone. `r` is the original-case, wake-stripped line."""
    m = _REMEMBER_RE.match(r.strip())
    if not m:
        return None
    rest = m.group(1).strip()
    if _WEARER_SUBJECT.match(rest):
        return None                          # a fact about you, not a person
    pm = _PERSON_PRONOUN.match(rest)
    if pm:
        fact = _strip_copula(pm.group(2).strip())
        return Intent("note_person", {"who": None, "note": fact}) if fact else None
    nm = _NAME_LEAD.match(rest)
    if nm and nm.group(1).lower() not in _NOT_A_NAME_WORD:
        fact = _strip_copula(nm.group(2).strip())
        if fact:
            return Intent("note_person", {"who": nm.group(1), "note": fact})
    return None


def detect_wake(text: str) -> tuple[bool, str]:
    """(heard_wake, remainder). True if a leading wake phrase is present; the
    remainder is whatever command followed it ('' if the wake stood alone)."""
    t = (text or "").strip()
    low = t.lower()
    for w in WAKE:
        # match the phrase as a whole leading token, not a prefix of a word
        if low == w or low.startswith(w + " ") or low.startswith(w + ","):
            return True, t[len(w):].lstrip(" ,.!—-").strip()
    return False, t


def strip_wake(text: str) -> str:
    """Drop a leading wake phrase (and stray punctuation) if present."""
    return detect_wake(text)[1]


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

    # Scholar — read what you're looking at. These are about the thing in view,
    # so they carry no query; the orchestrator pairs them with the current frame.
    # forms: "how do I fill this (out)[ to <purpose>]" / "help me fill this form"
    m = re.match(r"(?:how do i |help me )?fill (?:this|it|out|in|this form|this out)"
                 r"(?:\s+(?:out|in))?(?:\s+(?:to|for)\s+(.*))?$", t)
    if m or "fill this out" in t or "fill out this form" in t:
        purpose = (m.group(1).strip() if m and m.group(1) else "")
        return Intent("scholar", {"mode": "form", "purpose": purpose})
    # answers: "what's the answer", "answer this (question)", "solve this"
    if re.match(r"(?:what'?s the answer|answer (?:this|the question|it)|solve (?:this|it))\b", t) \
            or t in ("what is the answer", "the answer"):
        return Intent("scholar", {"mode": "answer"})
    # plain-words: "explain this", "what does this mean", "summarize this",
    # "put this in plain english/words", "translate the legal(ese)"
    if re.match(r"(?:explain (?:this|it)|what does (?:this|it) mean|summari[sz]e (?:this|it)|"
                r"(?:put (?:this|it) in )?plain (?:english|words|language)|"
                r"break (?:this|it) down)\b", t):
        return Intent("scholar", {"mode": "explain"})

    # "remember Maya's into climbing" — a note about a person you know
    note = _parse_person_note(r)
    if note is not None:
        return note

    # native timers / clock — Oracle builds these; no rehearsal needed
    tc = _parse_timer_clock(t)
    if tc is not None:
        return tc

    return Intent("ask", {"query": raw.strip()})
