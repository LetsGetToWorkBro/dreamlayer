"""consistency.py — Candor: does this contradict what you already recorded?

Display name: **Candor** — the inward twin of Truth Lens (Truth Lens judges
others' credibility; Candor keeps your own story honest). Class stays
ConsistencyEngine.

The privacy-respecting reimagining of "fact-check": no cloud, no web, no
external claim-of-truth. It only ever compares a new statement against
*your own* memories on the device, and flags when the two can't both be
true — "you said the meeting was at 3, now you're saying 4."

Three kinds of contradiction over a shared subject:
  negation  one side asserts, the other denies the same thing
  antonym   the two sides name opposite states (open/closed, on/off)
  value     the two sides give different numbers/times for the same thing

Everything is a deterministic, offline heuristic over the memory ring. It
never claims *which* statement is right — only that they disagree, so you
can notice. Private memories (meta.private) are never compared; the caller
gates the whole thing behind the Privacy Veil.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_TOKEN = re.compile(r"[a-z0-9:]+")
# Bare numbers AND clock times. The bare-number form alone missed the single
# case this module's own docstring uses as its example — "you said the meeting
# was at 3, now you're saying 4" — whenever either side was written the way
# people actually say it. `\b\d{1,4}\b` cannot match the "3" in "3pm": the
# trailing `\b` needs a non-word character and gets `p`. So "the lease is at
# 3pm" vs "the lease is at 4pm" extracted NO numbers from either side and the
# value branch could not fire. Clock forms are matched first so "3:30pm" is one
# token rather than a bare 3.
_NUM = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b|\b\d{1,4}(?::\d{2})?\b")

_NEGATORS = frozenset({
    "not", "no", "never", "none", "cannot", "cant", "nope", "without",
    "isnt", "arent", "wasnt", "werent", "wont", "dont", "doesnt", "didnt",
    "cant", "couldnt", "wouldnt", "shouldnt", "aint", "nothing",
})

# opposite states — if one side has a, the other b, over a shared subject
_ANTONYMS = [
    ("open", "closed"), ("on", "off"), ("up", "down"), ("in", "out"),
    ("cheap", "expensive"), ("early", "late"), ("free", "busy"),
    ("true", "false"), ("yes", "no"), ("win", "lose"), ("won", "lost"),
    ("alive", "dead"), ("full", "empty"), ("hot", "cold"), ("left", "right"),
    ("start", "end"), ("began", "ended"), ("increase", "decrease"),
    ("up", "off"), ("paid", "unpaid"), ("done", "pending"),
]

_STOP = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "at", "it",
    "is", "was", "be", "will", "for", "that", "this", "with", "you",
    "your", "i", "we", "he", "she", "they", "them", "my", "me", "are",
    "were", "so", "but", "as", "by", "from", "have", "has", "had",
    "about", "there", "their", "his", "her", "our",
}) | _NEGATORS


def _words(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _keywords(text: str) -> set[str]:
    return {w for w in _words(text) if w not in _STOP and len(w) >= 3
            and not w.isdigit()}


def _has_negator(words: list[str]) -> bool:
    return any(w in _NEGATORS for w in words)


# Irregular past forms the suffix rules below cannot reach. Deliberately tiny:
# every entry here is a verb that appears in a promise or a plan, which is what
# this engine reads. A general stemmer would collapse unrelated words and turn
# misses into false accusations, which is the strictly worse failure.
_IRREGULAR = {
    "sent": "send", "paid": "pay", "said": "say", "told": "tell",
    "bought": "buy", "sold": "sell", "made": "make", "met": "meet",
    "left": "leave", "kept": "keep", "took": "take", "gave": "give",
    "wrote": "write", "spoke": "speak", "brought": "bring", "built": "build",
    "found": "find", "held": "hold", "lent": "lend", "booked": "book",
}


def _norm(word: str) -> str:
    """Fold a word to a comparison form. Suffix rules only, after the table.

    This exists because the subject gate counts SHARED keywords, and "I sent
    the invoice" vs "I did not send the invoice" shared exactly one — "invoice"
    — so the clearest contradiction in the file's own idiom fell one short of
    the threshold and returned None. `sent`/`send` is not a suffix difference,
    hence the table. Order matters: check the table before stripping, or
    "sent" loses its final `t` to no rule and stays unmatched.
    """
    w = _IRREGULAR.get(word, word)
    if len(w) > 4 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2] if not w.endswith("eed") else w
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


_CLOCK = re.compile(r"^\d{1,2}(?::\d{2})?\s?(?:am|pm)$|^\d{1,2}:\d{2}$")


def _num_kind(nums: set) -> str:
    """"clock" when every extracted number is a time of day, else "plain".

    Comparability, not formatting. Two times of day disagreeing about the same
    appointment is a contradiction; a time of day and a duration are simply two
    different measurements — "the meeting is at 3pm" vs "the meeting ran 4
    hours" are both true, and the relaxed gate below would otherwise report
    them as a clash on the strength of one shared word.
    """
    if not nums:
        return ""
    return "clock" if all(_CLOCK.match(n) for n in nums) else "plain"


_NAME = re.compile(r"\b[A-Z][a-z]{2,}\b")


def _named(text: str) -> set[str]:
    """Capitalised, non-sentence-word tokens — a cheap stand-in for "who or what
    this line is about", available with no NER and no model.

    Sentence-initial position is NOT excluded. It costs a few false names ("The
    lease…"), and those are filtered by `_STOP` anyway, whereas excluding it
    would blind the check to every line that simply starts with the person's
    name — which is most of them.
    """
    return {w.lower() for w in _NAME.findall(text or "")
            if w.lower() not in _STOP}


def contradicts(claim: str, prior: str, min_shared: int = 2):
    """Pairwise contradiction test over a shared subject. Returns
    (reason, detail) or None. Shared by Candor and the Provenance Lens.

    NOTE for anyone tuning the thresholds: the two error directions are not
    symmetric. A miss makes Candor quiet. A false fire pushes a card that tells
    the wearer they contradicted themselves, quoting a sentence that was about
    something else — so every relaxation below is paired with the case it must
    still refuse, and `test_consistency.py` carries a corpus of both.
    """
    # DIFFERENT NAMED SUBJECTS. "Ana is coming to dinner" vs "Bob is not coming
    # to dinner" shares "coming" and "dinner" — two keywords, so it clears the
    # gate — and then trips the negator asymmetry. It fired before this pass and
    # it was always wrong: two people, two facts, no contradiction. When both
    # lines name someone and the names are disjoint, they are not the same
    # claim, whatever else they share.
    #
    # Only applies when BOTH sides name something: transcripts arrive lowercased
    # from some ASR engines, and a rule that fired on "one side has no names"
    # would suppress every genuine contradiction in those.
    cnames, pnames = _named(claim), _named(prior)
    if cnames and pnames and not (cnames & pnames):
        return None
    claim_words = _words(claim)
    pwords = _words(prior)
    cnums = set(_NUM.findall(claim.lower()))
    pnums = set(_NUM.findall(prior.lower()))

    # THE SUBJECT GATE. Two shared keywords means "these are about the same
    # thing"; below that, any disagreement found is between unrelated lines and
    # firing would accuse the wearer of contradicting themselves at random.
    #
    # It was also, measurably, what suppressed most true positives. Two changes,
    # each narrow enough to name what it does and does not admit:
    #
    #   * keywords are compared in NORMALISED form, so send/sent and book/booked
    #     count as the shared word they plainly are.
    #   * a number PRESENT ON BOTH SIDES counts as one shared keyword. "the
    #     meeting is at 3" vs "the meeting is not at 3" shares only "meeting"
    #     once digits are dropped, so an explicit, unambiguous negation could
    #     never be reached. A number both sides agree on is exactly the evidence
    #     that they are about the same appointment.
    #
    # What this deliberately does NOT do is lower the threshold to 1. "Ana is
    # coming" vs "Bob is not coming" shares "coming" and nothing else, and a
    # gate of 1 would report that as the wearer contradicting themselves. A
    # missed contradiction is a lens that is quiet; a false one is a lens that
    # calls you a liar about a sentence you never said.
    shared = {_norm(w) for w in _keywords(claim)} & {_norm(w) for w in _keywords(prior)}
    evidence = len(shared)

    # COMPARABLE MEASUREMENTS also count as subject evidence, and this is what
    # the module's own headline example needs: "the meeting is at 3pm" vs "the
    # meeting is at 4pm" shares exactly one content word — "meeting" — because
    # the times ARE the disagreement and so cannot also be the shared subject.
    # Two clock times about one appointment is precisely the case this file
    # exists for, and it scored 1 and was dropped.
    #
    # `_num_kind` is what keeps this narrow. The relaxation applies only when
    # both sides measure the SAME KIND of thing, so "the meeting is at 3pm" vs
    # "the meeting ran 4 hours" — a time and a duration, both true — does not
    # qualify. Without that check this rule would manufacture exactly the sort
    # of false accusation the gate is there to prevent.
    # AT MOST ONE point from the numbers, and the two cases are mutually
    # exclusive. Stacking them was a real regression caught by the corpus: "the
    # meeting is at 3" vs "the invoice is not 3 pages" shares NO content word,
    # and awarding a point for "same number" and a second for "same kind of
    # number" — over the one identical "3" — carried it to the threshold and
    # fired a negation on two unrelated lines.
    if cnums & pnums:
        evidence += 1                     # the same value: one appointment
    elif cnums and pnums and _num_kind(cnums) == _num_kind(pnums):
        evidence += 1                     # different values, same measurement

    if evidence < min_shared:
        return None                       # not clearly the same subject
    if _has_negator(claim_words) != _has_negator(pwords):
        return ("negation", "one asserts, one denies")
    pset, cset = set(pwords), set(claim_words)
    for a, b in _ANTONYMS:
        if (a in pset and b in cset) or (b in pset and a in cset):
            return ("antonym", f"{a} vs {b}")
    if pnums and cnums and pnums.isdisjoint(cnums):
        return ("value", f"{sorted(pnums)[0]} vs {sorted(cnums)[0]}")
    return None


@dataclass
class ConsistencyResult:
    fired: bool
    reason: str            # "" | "negation" | "antonym" | "value"
    prior_summary: str
    new_summary: str
    detail: str            # the specific clash (the antonym pair, the values)
    card: Optional[dict]


class ConsistencyEngine:
    """Compares a new statement against your recorded memories."""

    def __init__(self, ring, *, lookback: int = 40,
                 min_shared: int = 2, min_prior_confidence: float = 0.30):
        self.ring = ring
        self.lookback = lookback
        self.min_shared = min_shared
        self.min_prior_confidence = min_prior_confidence

    def _baseline(self):
        out = []
        for b in self.ring.latest(limit=self.lookback):
            ev = b.event
            if (getattr(ev, "meta", None) or {}).get("private"):
                continue                      # private is never compared
            if float(getattr(ev, "confidence", 0.0) or 0.0) < self.min_prior_confidence:
                continue
            out.append(ev)
        return out

    def check(self, claim: str, now: Optional[float] = None) -> ConsistencyResult:
        """Compare `claim` against the memory baseline for a contradiction."""
        for ev in self._baseline():
            prior = getattr(ev, "summary", "") or ""
            clash = contradicts(claim, prior, self.min_shared)
            if clash is not None:
                return self._fire(clash[0], prior, claim, clash[1])
        return ConsistencyResult(False, "", "", claim, "", None)

    def _fire(self, reason, prior, claim, detail) -> ConsistencyResult:
        return ConsistencyResult(
            fired=True, reason=reason, prior_summary=prior,
            new_summary=claim, detail=detail,
            card=_consistency_card(prior, claim, reason, detail))


def _consistency_card(prior: str, claim: str, reason: str, detail: str) -> dict:
    return {
        "type": "ConsistencyCard",
        "dismiss_ms": 5000,
        "eyebrow": "You said different before",
        "primary": claim,
        "footer": prior,
        "reason": reason,
        "detail": detail,
        "color": "accent_attention",
        "lines": ["You said different before", claim, "earlier:", prior],
    }
