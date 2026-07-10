"""orchestrator/voice.py — "Hey Juno" wake + intent routing.

Hands-free is the whole point of glasses, so this turns a spoken line into a
structured intent the orchestrator can act on. The microphone + speech-to-text
is a device seam (ASR isn't done here); this layer takes the *transcribed
text*, strips the wake phrase (detect_wake), and figures out what you meant:

    "Hey Juno, what did Marcus need?"       → recall(query)
    "where did I leave my bike?"              → locate(subject="bike")
    "reply to Priya saying on my way"         → reply(to="Priya", text="on my way")
    "I left my bike at the north rack"        → stash(subject="bike", place="the north rack")
    "I'm parked on level 3"                   → stash(subject="the car", place="level 3")
    "my car's in the garage"                  → stash(subject="car", place="the garage")
    "where did I park?"                       → locate(subject="car")
    ("my mom is in the hospital" is NOT a stash — person/event/idiom subjects
     stand down and fall through to ask; see _STASH_NOT_A_THING)
    "remember Maya's into rock climbing"      → note_person(who="Maya", note="into rock climbing")
    "remember she works at Google"            → note_person(who=None, note="works at Google")
    "this is my colleague Sarah, she's a PM"  → meet_person(who="Sarah", relation="colleague", note="she's a PM")
    "Marcus owes me $20" / "I owe Dana lunch"  → debt(who, dir=they_owe|i_owe, what)
    "Marcus paid me back"                     → debt_settle(who="Marcus")
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

# Juno is DreamLayer's assistant. "Hey Juno" is the primary wake phrase;
# the rest are graceful variants (and the old DreamLayer names, kept working).
ASSISTANT_NAME = "Juno"
WAKE = ("hey juno", "ok juno", "okay juno", "juno",
        "hey dreamlayer", "ok dreamlayer", "dreamlayer")


@dataclass
class Intent:
    kind: str                       # recall|locate|stash|reply|brief|missed|scholar|ask
    args: dict = field(default_factory=dict)


# -- native timers & clock: the everyday behaviors Juno just builds --------

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


# -- debts & favors: "Marcus owes me $20" / "I owe Dana lunch" ---------------

_DEBT_THEY = re.compile(r"^(.+?)\s+owes?\s+(?:me|you)\s+(.+)$", re.I)
_DEBT_I = re.compile(r"^i\s+owe\s+(\w[\w'’.\-]*)\s+(.+)$", re.I)
_SETTLE_A = re.compile(
    r"^(?:i\s+)?(?:paid\s+(?:back\s+)?|settled\s+up\s+with\s+|squared\s+up\s+with\s+|"
    r"we(?:'re| are)\s+(?:even|square)\s+with\s+|clear\s+with\s+)(\w[\w'’.\-]*)", re.I)
_SETTLE_B = re.compile(r"^(\w[\w'’.\-]*)\s+(?:paid|got)\s+me\s+back\b", re.I)
_PRONOUNS = {"he", "she", "they", "him", "her", "them"}


def _clean_amount(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip(" .,!?")).strip()


def _parse_debt(r: str) -> "Intent | None":
    """A debt/favor you want tracked per person, or None. `r` is original case."""
    core = r.strip()
    m = re.match(r"^(?:remember|note)(?:\s+that)?\s+(.+)$", core, re.I)
    if m:
        core = m.group(1).strip()
    ms = _SETTLE_A.match(core) or _SETTLE_B.match(core)
    if ms:
        return Intent("debt_settle", {"who": ms.group(1)})
    mi = _DEBT_I.match(core)
    if mi:
        return Intent("debt", {"who": mi.group(1), "dir": "i_owe",
                               "what": _clean_amount(mi.group(2))})
    mt = _DEBT_THEY.match(core)
    if mt:
        who = mt.group(1).strip()
        who = None if who.lower() in _PRONOUNS else who
        return Intent("debt", {"who": who, "dir": "they_owe",
                               "what": _clean_amount(mt.group(2))})
    return None


# -- stash: "I left my bike at the north rack" -> where you put a thing --------

_LOC = r"(?:at|in|on|by|near|under|underneath|inside|behind|next\s+to|beside)"

# "my X is at Y" / "I left my X at Y" phrasings that AREN'T a misplaced thing:
# people (that's social memory, not a stash), events and times, idioms, body
# parts, and the native behaviors (timer/alarm). A subject hit here makes the
# stash parser stand down — the line degrades to `ask`, which is always safe.
# Better to answer a question than to confidently mis-file your mom as an
# object ("Got it — your mom is at the hospital").
_STASH_NOT_A_THING = frozenset("""
    mom mother dad father parent parents brother brothers sister sisters wife
    husband partner boyfriend girlfriend son daughter kid kids child children
    family friend friends buddy boss coworker colleague roommate aunt uncle
    cousin grandma grandmother grandpa grandfather nephew niece baby sitter
    nanny doctor dentist therapist team guy guys everyone everybody
    job work career shift meeting appointment interview call class lecture
    exam test flight train bus ride birthday anniversary wedding party dinner
    lunch breakfast reservation game match show concert
    faith heart mind trust hope luck life word words promise message voicemail
    ball eye eyes head back foot feet hand hands
    alarm timer clock countdown reminder alert
    early late everything nothing
""".split())

# Places that are really times, modes, or people — "at 3", "on Friday",
# "on silent", "in you". Not somewhere a thing can be found later.
_STASH_NOT_A_PLACE = re.compile(
    r"^(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|o'?clock)?|noon|midnight|dawn|dusk|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"today|tonight|tomorrow|yesterday|"
    r"silent|mute|vibrate|hold|do\s+not\s+disturb|"
    r"you|me|him|her|them|us|it|that)[.!]?$", re.I)

_STASH_LEFT = re.compile(
    r"^(?:i\s+)?(?:left|put|stashed?|dropped|stowed|set)\s+"
    r"(?:my\s+|the\s+|our\s+|a\s+|an\s+)?(.+?)\s+" + _LOC + r"\s+(.+)$", re.I)
# adverb places carry no preposition: "I left my bike downstairs"
_STASH_ADV = re.compile(
    r"^(?:i\s+)?(?:left|put|stashed?|dropped|stowed|set)\s+"
    r"(?:my\s+|the\s+|our\s+)?(.+?)\s+"
    r"(downstairs|upstairs|outside|inside|out\s+front|out\s+back)$", re.I)
# "I parked on level 3" / "I'm parked in the garage" / "we parked at the far
# end". The pronoun and the place are both required — a bare "I parked the
# car" carries nothing worth remembering.
_STASH_PARKED = re.compile(
    r"^(?:i|i'?m|i\s+am|we|we'?re|we\s+are)\s+parked\s+(?:the\s+car\s+)?"
    + _LOC + r"\s+(.+)$", re.I)
# "my keys are on the desk" / "my car's in the garage" (contraction too)
_STASH_IS = re.compile(
    r"^(?:my|our)\s+(.+?)(?:['’]s|\s+(?:is|are))\s+" + _LOC + r"\s+(.+)$", re.I)


def _clean_subject(s: str) -> str:
    return re.sub(r"^(?:my|the|our|a|an)\s+", "", (s or "").strip(), flags=re.I).strip()


def _stashable(subj: str, place: str) -> bool:
    """True only when the subject reads like a thing and the place like a
    place. Tokens are checked so "spare key" passes and "my little brother"
    doesn't."""
    if not subj or not place:
        return False
    tokens = {t.strip("'’.,!?").lower() for t in subj.split()}
    if tokens & _STASH_NOT_A_THING:
        return False
    return not _STASH_NOT_A_PLACE.match(place.strip())


def _parse_stash(r: str) -> "Intent | None":
    """"I left my bike at the north rack" / "I'm parked on level 3" / "my car's
    in the garage" → remember where a thing is, so 'where's my bike?' can
    answer. `r` is the original-case line (place words are captured verbatim).
    Deliberately conservative: person/event/idiom subjects fall through to ask."""
    core = r.strip()
    m = re.match(r"^(?:remember|note)(?:\s+that)?\s+(.+)$", core, re.I)
    if m:
        core = m.group(1).strip()
    for rx in (_STASH_LEFT, _STASH_IS, _STASH_ADV):
        mm = rx.match(core)
        if mm:
            subj = _clean_subject(mm.group(1))
            place = mm.group(2).strip()
            if _stashable(subj, place):
                return Intent("stash", {"subject": subj, "place": place})
    mp = _STASH_PARKED.match(core)
    if mp:
        place = mp.group(1).strip()
        if _stashable("car", place):
            return Intent("stash", {"subject": "the car", "place": place})
    return None


def _parse_meet_person(r: str) -> "Intent | None":
    """"this is Sarah" / "remember this is my colleague Sarah, she runs
    marketing" / "meet my brother Dan" → meet someone on the spot: create the
    contact from the face in view + the name, seeding the dossier with the
    relationship and any trailing note. `r` is the original-case line."""
    from ..social_lens.introduction import parse_introduction_ex
    core = r.strip()
    m = re.match(r"^(?:remember|note|jot down|make a note)(?:\s+that)?\s+(.+)$",
                 core, re.I)
    if m:
        core = m.group(1).strip()
    parsed = parse_introduction_ex(core)      # (name, relation) or None
    if parsed is None:
        return None
    name, relation = parsed
    note = None
    idx = core.lower().find(name.lower())
    if idx >= 0:
        tail = core[idx + len(name):]
        tail = re.sub(r"^[\s,;:.\-–—]+", "", tail)         # drop the joiner
        tail = re.sub(r"^(?:and|who)\s+", "", tail, flags=re.I).strip()
        note = tail or None
    return Intent("meet_person", {"who": name, "relation": relation, "note": note})


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

    # where's my <thing> / where are my keys / where did I leave|put|park <thing>
    m = re.match(r"(?:where'?s|where is|where are|where did i (?:leave|put|park))\s+"
                 r"(?:my\s+|the\s+)?(.+)$", r, re.IGNORECASE)
    if m:
        return Intent("locate", {"subject": m.group(1).strip()})
    # bare parking retrieval — "where did I park", "where am I parked"
    if re.match(r"^where (?:did i park|do i park|am i parked)$", t):
        return Intent("locate", {"subject": "car"})

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

    # "Marcus owes me $20" / "I owe Dana lunch" — a debt on the person
    # (checked before meet/note so "owe" wins over a generic note)
    debt = _parse_debt(r)
    if debt is not None:
        return debt

    # "this is my colleague Sarah, she runs marketing" — meet someone new,
    # grabbing the face in view (checked before the plain note below)
    met = _parse_meet_person(r)
    if met is not None:
        return met

    # "remember Maya's into climbing" — a note about a person you know
    note = _parse_person_note(r)
    if note is not None:
        return note

    # native timers / clock — Juno builds these; no rehearsal needed. Checked
    # before stash so "put a clock on the hud" is a clock, not a stashed "clock".
    tc = _parse_timer_clock(t)
    if tc is not None:
        return tc

    # "I left my bike at the north rack" — remember where a thing is, so a later
    # "where's my bike?" can answer (checked after the person notes above)
    stash = _parse_stash(r)
    if stash is not None:
        return stash

    return Intent("ask", {"query": raw.strip()})
