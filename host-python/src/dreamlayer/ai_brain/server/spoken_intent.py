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
    # bare adjectives are never the head noun, and leaving them in front of it
    # defeated the head test: "have you seen the NEW season" made "new" the head
    "new", "old", "next", "one", "another", "other", "same", "whole", "very",
}

# "I lost my ___" is an idiom far more often than a search. When every noun the
# wearer named is one of these, they were not asking the glasses to look.
_ABSTRACT = {
    "train", "thought", "thoughts", "mind", "way", "temper", "patience", "cool",
    "place", "appetite", "voice", "marbles", "nerve", "touch", "edge", "faith",
    "hope", "count", "track", "focus", "rhythm", "grip", "composure", "bearings",
    "confidence", "interest", "point", "words", "breath", "sleep",
}

# --- what makes an utterance a COMMAND rather than talk ----------------------
# Three structural tests, applied to every rule rather than to four of them:
#
#   1. ONE CLAUSE. Only the first clause is considered, for matching AND for the
#      nouns. "where are my keys. the weather is nice" used to hand the search
#      "weather"; "i can't find my notes from the standup" used to match because
#      "find" and "my" both appeared SOMEWHERE in it.
#   2. THE TARGET IS THE VERB'S OBJECT. `find … my` anywhere in a sentence is not
#      a request; `find my <thing>` is. Every cue now names its determiner
#      directly, so "did you find my email" cannot match on proximity.
#   3. IT IS ADDRESSED TO THE GLASSES. An imperative starts the utterance, and a
#      leading second-person or narrative subject ("did you", "let me", "i'll",
#      "i read") means the wearer is talking to a person about a thing, not
#      asking to look at it.
_DEIC = r"(?:this|that|these|those|it)"
_DET = r"(?:my|our|the)"
_MINE = r"(?:my|our)"
_END = r"\s*[.?!]*\s*$"
# Things you say TO an assistant. Anything else trailing the object means the
# sentence was going somewhere else: "translate this FOR ME" is a request,
# "translate that FOR THE BOARD" is an instruction to a colleague.
_TAIL = (r"(?:\s+(?:for me|to me|out to me|out loud|aloud|please|now|again|"
         r"quick|quickly|will you|would you))*" + _END)
# Fillers a speech service leaves in the middle of a phrase.
_FILLER = re.compile(r"[,\s]*\b(?:uh|um+|er+|erm|hmm+|like|you know|i mean)\b[,\s]*",
                     re.I)
# A leading subject that makes the sentence about a PERSON doing something.
_NOT_ADDRESSED = re.compile(
    r"^(?:"
    r"(?:did|do|does|can|could|would|will|should) (?:you|we|he|she|they)\b"
    r"|let'?s\b|let me\b|(?:i|you|we|they|he|she)'?(?:ll|d|ve|re)\b"
    r"|i (?:read|already|just|once|never|always|think|thought|love|hate)\b"
    r"|we'?ve\b|it'?s\b"
    r")", re.I)

# A camera searches the VISIBLE WORLD. These are things it can never find, and
# every one of them was a live false search: people ("where is my son", "have you
# seen my wife"), abstractions ("where is my motivation"), the body ("where's my
# head today"), and things that live inside a screen ("did you find my email").
_UNFINDABLE = {
    # people
    "son", "daughter", "wife", "husband", "partner", "mother", "father", "mum",
    "mom", "dad", "kid", "kids", "child", "children", "baby", "men", "women",
    "family", "friend", "friends", "boss", "team", "boy", "girl", "brother",
    "sister", "grandma", "grandpa", "people", "man", "woman",
    # the body
    "head", "hand", "hands", "foot", "feet", "hair", "face", "eyes", "leg",
    # abstractions and idioms
    "motivation", "dignity", "temper", "train", "thought", "thoughts", "mind",
    "way", "patience", "cool", "place", "appetite", "voice", "marbles", "nerve",
    "touch", "edge", "faith", "hope", "count", "track", "focus", "rhythm",
    "grip", "composure", "bearings", "confidence", "interest", "point", "words",
    "breath", "sleep", "life", "job", "mojo", "things", "stuff", "money",
    # inside a screen, not in the room
    "email", "emails", "message", "messages", "text", "texts", "notes", "note",
    "file", "files", "folder", "password", "wifi", "calendar", "inbox", "photo",
    "photos", "playlist", "contact", "contacts", "number", "address", "link",
    # what a "find" phrasing means when it is really about work or media
    "difference", "problem", "problems", "issue", "bug", "reason", "answer",
    "solution", "cause", "error", "season", "episode", "film", "movie", "show",
    "news", "weather", "forecast", "price", "meaning", "word", "name", "time",
    "date", "flight", "train", "bus", "route", "recipe", "song", "video",
}

# Ordered: the FIRST pattern that matches wins, so a specific phrase ("how far")
# is never swallowed by a general one ("what is").
_RULES: tuple[tuple[str, str], ...] = (
    # --- find: the intent that cannot exist without your words --------------
    (rf"^where(?:'?s| is| are| was| were| did i (?:leave|put)| ?'?d i (?:leave|put)|"
     rf" do i keep)\s+{_DET}\s+\S+(?:\s+\S+){{0,2}}{_TAIL}", "find"),
    (rf"^(?:find|locate|look for|spot|help me find)\s+{_DET}\s+"
     rf"\S+(?:\s+\S+){{0,3}}{_TAIL}", "find"),
    (rf"^i (?:can'?t|cannot) find\s+{_DET}\s+\S+(?:\s+\S+){{0,2}}{_TAIL}", "find"),
    (rf"^i (?:lost|misplaced)\s+{_MINE}\s+\S+(?:\s+\S+){{0,1}}{_TAIL}", "find"),
    (rf"^have you seen\s+{_DET}\s+\S+(?:\s+\S+){{0,1}}{_TAIL}", "find"),
    # --- distance -----------------------------------------------------------
    # "how far is THAT", not "how far we've come" / "how far is that from done".
    (rf"^how (?:far|close|deep|near|tall|high|big|wide)\s+"
     rf"(?:away\s+)?(?:is|are)\s+(?:{_DEIC}|the)\s*\S*{_TAIL}", "depth"),
    (rf"^how many (?:feet|metres|meters|steps|paces)\s+(?:to|away)"
     rf"(?:\s+{_DEIC})?{_TAIL}", "depth"),
    (rf"^(?:what(?:'?s| is) the )?distance to {_DEIC}{_TAIL}", "depth"),
    # --- the sky ------------------------------------------------------------
    (rf"^(?:what|which) (?:star|stars|planet|constellation)\s+(?:is|are)\s+"
     rf"(?:{_DEIC}){_TAIL}", "sky"),
    (rf"^what(?:'?s| is) (?:that|this) (?:star|planet|constellation){_TAIL}", "sky"),
    (rf"^is that (?:a |the )?(?:star|planet|satellite|iss|space station){_TAIL}", "sky"),
    (rf"^name (?:the sky|that star|the constellation){_TAIL}", "sky"),
    (rf"^what am i looking at up there{_TAIL}", "sky"),
    # --- translate ----------------------------------------------------------
    (rf"^translate {_DEIC}{_TAIL}", "translate"),
    (rf"^translate (?:{_DEIC}|the) "
     rf"(?:sign|menu|label|text|page|line|word){_TAIL}", "translate"),
    (rf"^what does {_DEIC} (?:mean|say) in \w+{_TAIL}", "translate"),
    (rf"^(?:say|read) {_DEIC} in english{_TAIL}", "translate"),
    # --- compare (TasteLens) ------------------------------------------------
    (rf"^compare (?:{_DEIC}|them|the two){_TAIL}", "compare"),
    (rf"^which (?:of (?:these|them|those)|one)\b.{{0,30}}?"
     rf"\b(?:better|best|healthier|cheaper|stronger|worse|less|more|fresher|"
     rf"safer|should i)\b.{{0,12}}{_TAIL}", "compare"),
    (rf"^which of (?:these|them|those){_TAIL}", "compare"),
    (rf"^what should i (?:pick|choose|buy|get)(?: here)?{_TAIL}", "compare"),
    # --- maths --------------------------------------------------------------
    (rf"^(?:solve|calculate|compute) {_DEIC}{_TAIL}", "math"),
    (rf"^work {_DEIC} out{_TAIL}", "math"),
    (rf"^what(?:'?s| is) the answer{_TAIL}", "math"),
    (rf"^what does {_DEIC} (?:equal|come to|add up to){_TAIL}", "math"),
    # --- read ---------------------------------------------------------------
    # Never a bare "read the ___": "read the room" is not a document. And always
    # utterance-initial, so "i read this book and it changed nothing" is not one.
    (rf"^read {_DEIC}{_TAIL}", "read"),
    (rf"^read (?:{_DEIC}|the) "
     rf"(?:sign|menu|label|page|screen|text|line|number){_TAIL}", "read"),
    (rf"^what does {_DEIC} say{_TAIL}", "read"),
    (rf"^what(?:'?s| is) {_DEIC} say{_TAIL}", "read"),
    (rf"^what(?:'?s| is) (?:written|printed) "
     rf"(?:here|there|on (?:this|that)){_TAIL}", "read"),
    # --- isolate ------------------------------------------------------------
    (rf"^(?:isolate|separate) {_DEIC}(?: one)?{_TAIL}", "segment"),
    (rf"^just (?:this|that) one{_TAIL}", "segment"),
    # --- identify (the weakest, so it never steals a specific phrase) -------
    (rf"^what(?:'?s| is| are)? (?:this|that|these|those){_TAIL}", "object"),
    (rf"^(?:identify|name) {_DEIC}{_TAIL}", "object"),
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


def _first_clause(text: str) -> str:
    """The first clause only. A request is one clause; everything after a comma or
    a full stop belongs to a different thought, and treating the whole utterance as
    one gave the search nouns from sentences the wearer never pointed at
    ("where are my keys. the weather is nice" → keys, weather, nice)."""
    t = _FILLER.sub(" ", str(text or ""))
    t = " ".join(t.split())
    for i, ch in enumerate(t):
        if ch in ".?!,;":
            return t[:i].strip()
    return t


def _terms(text: str) -> list:
    """The nouns being hunted, taken from what was actually said after the cue —
    never invented. Stopwords and the cue phrase itself are dropped."""
    t = re.sub(r"(?i)^(?:where(?:'?s| is| are| was| were| did i (?:leave|put)|"
               r"'?d i (?:leave|put)| do i keep)?|find|locate|look for|spot|"
               r"i (?:can'?t|cannot) find|i lost|i misplaced|have you seen|"
               r"help me find)\b", " ", text)
    words = [w for w in re.split(r"[^A-Za-z0-9'-]+", t.lower()) if w]
    out: list = []
    for w in words:
        if w in _STOP or len(w) < 2:
            continue
        if w not in out:
            out.append(w[:48])
        if len(out) >= MAX_TERMS:
            break
    return out


def parse_spoken_intent(text: str) -> "dict | None":
    """``{"intent", "lens", "terms", "said"}`` for a spoken phrase, else None.

    ``lens`` is the lens to RUN directly ("" when the intent should merely boost
    the arbiter's own bidding). ``terms`` is only ever populated from words the
    wearer actually said.

    English only, deliberately and knowably: every rule is an English pattern, so
    a French or Japanese request returns None and the arbiter guesses from the
    frame instead. That is the honest failure, but it IS a limit — the ear is
    multilingual and this is not."""
    raw = " ".join(str(text or "").split())[:MAX_TEXT]
    said = _first_clause(raw)
    if len(said) < 3:
        return None
    # Addressed to a person, not to the glasses.
    if _NOT_ADDRESSED.search(said):
        return None
    for rx, intent in _COMPILED:
        if rx.search(said):
            terms = _terms(said) if intent == "find" else []
            if intent == "find":
                if not terms:
                    return None      # "where is it" names nothing — don't guess
                if terms[0] in _UNFINDABLE:
                    return None      # a camera cannot find a person or a feeling
            return {"intent": intent, "lens": INTENT_RUN_LENS.get(intent, ""),
                    "terms": terms, "said": said}
    return None
