"""ai_brain/server/spoken_intent.py — what you SAID is not a guess about your
intent, it IS your intent.

Tier 3 of the glance work. Tiers 1–2 made the arbiter a good guesser: it reads
the frame, the phone's own detections, where your head is pointed and when. This
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
}

# Ordered: the FIRST pattern that matches wins, so a specific phrase ("how far")
# is never swallowed by a general one ("what is").
_RULES: tuple[tuple[str, str], ...] = (
    # --- find: the intent that cannot exist without your words --------------
    (r"\b(?:where(?:'?s| is| are| did| the hell)?)\b.*", "find"),
    (r"\b(?:find|locate|look for|spot|help me find|point out)\b.*", "find"),
    (r"\b(?:i (?:can'?t|cannot) find|i lost|have you seen)\b.*", "find"),
    # --- distance -----------------------------------------------------------
    (r"\bhow (?:far|close|deep|near|tall|high)\b", "depth"),
    (r"\b(?:distance|how many (?:feet|metres|meters|steps))\b", "depth"),
    # --- the sky ------------------------------------------------------------
    (r"\b(?:what|which) (?:star|planet|constellation)\b", "sky"),
    (r"\b(?:name the sky|what'?s up there|what am i looking at up there)\b", "sky"),
    (r"\bis that (?:a )?(?:star|planet|satellite|the iss)\b", "sky"),
    # --- translate ----------------------------------------------------------
    (r"\btranslate\b", "translate"),
    (r"\bwhat does (?:this|that|it) mean in \w+", "translate"),
    (r"\bin english\b", "translate"),
    # --- compare (TasteLens) ------------------------------------------------
    (r"\bcompare\b", "compare"),
    # "which of these is healthier", "which one has less sugar", "which is better"
    (r"\bwhich\b.{0,24}\b(?:better|best|healthier|cheaper|stronger|worse|"
     r"less|more|fresher|safer)\b", "compare"),
    (r"\bwhich (?:of (?:these|them|those)|one)\b", "compare"),
    (r"\b(?:what should i (?:pick|choose|buy|get))\b", "compare"),
    # --- maths --------------------------------------------------------------
    (r"\b(?:solve|what'?s the answer|work (?:this|it) out|calculate)\b", "math"),
    # --- read ---------------------------------------------------------------
    (r"\b(?:read (?:this|that|it|the)|what does (?:this|that|it) say)\b", "read"),
    (r"\b(?:read (?:this |that |it )?(?:out|aloud|to me))\b", "read"),
    (r"\bwhat'?s (?:written|printed) (?:here|there|on (?:this|that))\b", "read"),
    # --- isolate ------------------------------------------------------------
    (r"\b(?:isolate|just (?:this|that) one|separate (?:this|that))\b", "segment"),
    # --- identify (the weakest, so it never steals a specific phrase) -------
    (r"\bwhat(?:'?s| is| are)? (?:this|that|these|those)\b", "object"),
    (r"\b(?:identify|name) (?:this|that|it)\b", "object"),
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
    t = re.sub(r"(?i)\b(?:where(?:'?s| is| are| did)?|find|locate|look for|spot|"
               r"i (?:can'?t|cannot) find|i lost|have you seen|help me find|"
               r"point out)\b", " ", text)
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
            if intent == "find" and not terms:
                return None          # "where is it" names nothing — don't guess
            return {"intent": intent, "lens": INTENT_RUN_LENS.get(intent, ""),
                    "terms": terms, "said": said}
    return None
