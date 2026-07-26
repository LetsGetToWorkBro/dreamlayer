"""ai_brain/server/spoken_intent.py — what you SAID is not a guess about your
intent, it IS your intent.

Tier 3 of the glance work. Tiers 1–2 made the arbiter a good guesser: it reads
the frame, the phone's own detections, where the camera is pointed and when. This
closes the loop — when you speak, there is nothing left to infer.

    "where did I leave my keys"   → find,  terms=["keys"]
    "what does this say"          → read
    "how far is that"             → depth
    "what star is that"           → sky
    "which of these is healthier" → compare (TasteLens)
    "what's the answer"           → math

This is also the ONLY honest way to reach the `find` lens: it needs the nouns
you are hunting, and no bare frame supplies them. An arbiter that auto-fired
find would be inventing a search — so find is not a candidate, and instead
becomes available the moment you say what you're looking for.

The parser must be DIRECTED, and that is the hard part
-----------------------------------------------------
An earlier version keyed on bare verbs and question words — `where`, `find`,
`spot`, `point out`, `read the`, `how far`, `solve` — and an audit put 39 ordinary
conversational phrases through it: 26 of them fired a lens, and because a spoken
lens runs OUTRIGHT (before any bidding) those were actions, not soft errors.

    "how far we've come"                → depth  → "install the World Sense pack"
    "read the room"                     → doc
    "where there's smoke there's fire"  → find   terms=["smoke", "fire"]
    "I lost my train of thought"        → find   terms=["train", "thought"]
    "what's the answer to life"         → math
    "work it out between yourselves"    → math
    "isolate the variable in your thinking" → segment
    "is that a satellite office"        → sky

Every one of those is a figure of speech. What separates a command to the glasses
from talk is that a command POINTS AT SOMETHING — "this", "that", "my keys" —
and usually ends there. So each rule now requires a deictic ("this/that/it") or a
first-person possessive ("my/our"), several are anchored to the end of the
utterance ("work it out" is a command, "work it out between yourselves" is
advice), and the bare verbs that carry no target at all are gone. `_CORPUS_*` in
the tests pins both directions: the 26 idioms stay silent, and the real phrasings
still land.

Deliberately a pure function over text: no model, no network, no state. It runs
identically on a Brain-side on-device transcript (the Sharp Ears pack) and on the
phone's own speech service, so whichever ear you have, the lens obeys the words.
Unrecognised speech returns None — the arbiter then guesses as before, which is
the honest fallback, never a wrong lens fired on a misheard phrase.
"""
from __future__ import annotations

import re

# Filler that is never the thing you're looking for.
_STOP = {
    "the", "a", "an", "my", "our", "his", "her", "their", "your", "some", "any",
    "that", "this", "those", "these", "it", "them", "is", "are", "was", "were",
    "did", "do", "does", "i", "me", "we", "you", "again", "please", "at", "in",
    "on", "of", "for", "to", "left", "put", "last", "time", "somewhere",
    "anywhere", "around", "here", "there", "up", "down",
    # verbs that belong to the CUE, not to the thing being hunted
    "leave", "leaving", "lose", "lost", "seen", "see", "find", "finding",
    "put", "placed", "remember", "know", "where", "what", "which",
    "misplaced", "keep", "help",
    # prepositions and pronouns are never the hunted noun, and leaving them in
    # defeated the idiom guard below: "I lost my patience with him" kept "with"
    # and "him" as terms, so not every term was abstract and it read as a search.
    "with", "about", "from", "by", "over", "under", "into", "and", "or", "but",
    "him", "them", "us", "she", "he", "they", "myself", "yourself", "so",
    "completely", "totally", "entirely", "already", "almost", "really", "just",
    "quite", "somehow", "utterly", "today", "yesterday", "earlier",
}

# "I lost my ___" is an idiom far more often than a search. When every noun the
# wearer named is one of these, they were not asking the glasses to look.
_ABSTRACT = {
    "train", "thought", "thoughts", "mind", "way", "temper", "patience", "cool",
    "place", "appetite", "voice", "marbles", "nerve", "touch", "edge", "faith",
    "hope", "count", "track", "focus", "rhythm", "grip", "composure", "bearings",
    "confidence", "interest", "point", "words", "breath", "sleep",
}

# What makes an utterance a command rather than talk: it points at something.
_DEIC = r"(?:this|that|these|those|it)"
_MINE = r"(?:my|our)"
_END = r"\s*[.?!]*\s*$"        # …and often stops right there

# Ordered: the FIRST pattern that matches wins, so a specific phrase ("how far")
# is never swallowed by a general one ("what is").
_RULES: tuple[tuple[str, str], ...] = (
    # --- find: the intent that cannot exist without your words --------------
    # Always about something of YOURS. Without that clause, "where do you see
    # yourself in five years" and "let's find out" were searches.
    (rf"\bwhere(?:'?s| is| are| did| do)\b[^.?!]*\b{_MINE}\b", "find"),
    (rf"\b(?:find|locate|look for|help me find)\b[^.?!]*\b{_MINE}\b", "find"),
    (rf"\bi (?:can'?t find|cannot find|lost|misplaced)\b[^.?!]*\b{_MINE}\b", "find"),
    (rf"\bhave you seen\b[^.?!]*\b{_MINE}\b", "find"),
    # --- distance -----------------------------------------------------------
    # "how far is THAT", not "how far we've come" / "how tall was your father".
    (rf"\bhow (?:far|close|deep|near|tall|high|big|wide)\b[^.?!]*"
     rf"\b(?:{_DEIC}|away)\b", "depth"),
    (rf"\bhow many (?:feet|metres|meters|steps|paces)\b[^.?!]*"
     rf"\b(?:{_DEIC}|away)\b", "depth"),
    (rf"\b(?:what(?:'?s| is) the )?distance to {_DEIC}\b", "depth"),
    # --- the sky ------------------------------------------------------------
    (rf"\b(?:what|which) (?:star|planet|constellation)\b[^.?!]*\b{_DEIC}\b", "sky"),
    (r"\bwhat(?:'?s| is) that (?:star|planet|constellation)\b", "sky"),
    # anchored to the END, so "is that a satellite OFFICE" is not the heavens
    (rf"\bis that (?:a |the )?(?:star|planet|satellite|iss|space station){_END}", "sky"),
    (r"\bname (?:the sky|that star|the constellation)\b", "sky"),
    (r"\bwhat am i looking at up there\b", "sky"),
    # --- translate ----------------------------------------------------------
    # "translate this" / "translate that sign" — but "translate that for the
    # board" is an instruction to a person, so the object has to be a thing in
    # view or the utterance has to stop there.
    (rf"\btranslate {_DEIC}{_END}", "translate"),
    (rf"\btranslate (?:{_DEIC}|the) (?:sign|menu|label|text|page|line|word)\b",
     "translate"),
    (rf"\bwhat does {_DEIC} (?:mean|say) in \w+", "translate"),
    (rf"\b(?:say|read) {_DEIC} in english\b", "translate"),
    # --- compare (TasteLens) ------------------------------------------------
    (rf"\bcompare (?:{_DEIC}|them|the two)\b", "compare"),
    # "which of these is healthier", "which one has less sugar", "which is better"
    (r"\bwhich\b.{0,24}\b(?:better|best|healthier|cheaper|stronger|worse|"
     r"less|more|fresher|safer)\b", "compare"),
    (r"\bwhich (?:of (?:these|them|those)|one)\b", "compare"),
    (r"\bwhat should i (?:pick|choose|buy|get)\b", "compare"),
    # --- maths --------------------------------------------------------------
    # "solve this", "work it out" — but not "calculate the risk of telling her"
    # or "work it out between yourselves", which is advice to a person.
    (rf"\b(?:solve|calculate|compute) {_DEIC}\b", "math"),
    (rf"\bwork {_DEIC} out{_END}", "math"),
    (rf"\bwhat(?:'?s| is) the answer{_END}", "math"),
    (rf"\bwhat does {_DEIC} (?:equal|come to|add up to)\b", "math"),
    # --- read ---------------------------------------------------------------
    # Never a bare "read the ___": "read the room" is not a document.
    (rf"\bread {_DEIC}\b", "read"),
    (rf"\bwhat does {_DEIC} say\b", "read"),
    (r"\bwhat(?:'?s| is) (?:written|printed) (?:here|there|on (?:this|that))\b", "read"),
    (r"\bread (?:the )?(?:sign|menu|label|page|screen)\b", "read"),
    # --- isolate ------------------------------------------------------------
    (rf"\b(?:isolate|separate) {_DEIC}\b", "segment"),
    (r"\bjust (?:this|that) one\b", "segment"),
    # --- identify (the weakest, so it never steals a specific phrase) -------
    (r"\bwhat(?:'?s| is| are)? (?:this|that|these|those)\b", "object"),
    (rf"\b(?:identify|name) {_DEIC}\b", "object"),
)

_COMPILED = tuple((re.compile(p, re.I), intent) for p, intent in _RULES)

# What the wearer said → the lens key WorldLensHost.look_lens executes. The
# arbiter's INTENT_LENS maps intents to CANDIDATE keys; this maps them to the
# lens that actually runs, which differs for read (candidate "read" → lens "doc").
INTENT_RUN_LENS = {
    "find": "find", "depth": "depth", "sky": "sky", "read": "doc",
    "math": "math", "segment": "segment",
    # compare/translate/object are reached through the object-lens path, which the
    # arbiter owns — a spoken hint boosts their bid instead of bypassing it.
    "compare": "", "translate": "", "object": "",
}

MAX_TEXT = 240          # a spoken phrase, not a document
MAX_TERMS = 4


def _terms(text: str) -> list:
    """The nouns being hunted, taken from what was actually said after the cue —
    never invented. Stopwords and the cue phrase itself are dropped."""
    t = re.sub(r"(?i)\b(?:where(?:'?s| is| are| did| do)?|find|locate|look for|"
               r"i (?:can'?t|cannot) find|i lost|i misplaced|have you seen|"
               r"help me find)\b", " ", text)
    words = [w for w in re.split(r"[^A-Za-z0-9'-]+", t.lower()) if w]
    out: list = []
    for w in words:
        if w in _STOP or len(w) < 2:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= MAX_TERMS:
            break
    return out


def parse_spoken_intent(text: str) -> "dict | None":
    """``{"intent", "lens", "terms", "said"}`` for a spoken phrase, else None.

    ``lens`` is the lens to RUN directly ("" when the intent should merely boost
    the arbiter's own bidding). ``terms`` is only ever populated from words the
    wearer actually said."""
    said = " ".join(str(text or "").split())[:MAX_TEXT]
    if len(said) < 3:
        return None
    for rx, intent in _COMPILED:
        if rx.search(said):
            terms = _terms(said) if intent == "find" else []
            if intent == "find":
                if not terms:
                    return None      # "where is it" names nothing — don't guess
                if all(t in _ABSTRACT for t in terms):
                    return None      # "I lost my train of thought" is not a search
            return {"intent": intent, "lens": INTENT_RUN_LENS.get(intent, ""),
                    "terms": terms, "said": said}
    return None
