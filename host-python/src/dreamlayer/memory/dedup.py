"""Near-duplicate collapsing over what the wearer is about to be SHOWN.

WHY THIS IS A READ-TIME PASS AND NOT A WRITE-TIME ONE
----------------------------------------------------
The obvious place to dedup is the store, and it is the wrong one. The Object
Lens's "seen before 5× · last at the kitchen" row is `len(seen)` over raw ring
entries (`object_lens/providers.MemoryProvider.build`) — repeats there are the
signal, not noise. Collapsing them at write time would silently turn every
count into 1 and the row would start lying about the wearer's own history.

At read time both things can be true at once: the count keeps reading the raw
ring, and the list the wearer scrubs through stops showing them the same
sentence five times.

WHY NOT mem0
------------
`memory_dedup` is catalogued against `mem0`, whose `Memory()` routes extraction
and embedding through a cloud LLM by default — this repo's own audit calls the
package "cloud-routing". Sending the wearer's memories to a third party to
notice that two of them are similar is not a trade this product can make, and
an optional dependency that silently changes where the data goes is not the
kind of optional this repo means. So the collapsing is here, dependency-free,
and it is what runs.

WHAT "NEAR" MEANS
-----------------
Token-set overlap after normalisation, which is deliberately dumber than an
embedding and has the property that matters: it is explainable. "call the
dentist" and "gotta ring the dentist" share `dentist`; whether they collapse is
a number you can look up, not a model's opinion. Cheap enough to run on every
read of a bounded list.
"""
from __future__ import annotations

import re
from typing import Callable, Sequence

#: Jaccard overlap at or above which two entries are "the same thing said
#: twice". Tuned to collapse a restated commitment while keeping two different
#: commitments about the same person apart — see `test_memory_dedup.py`, which
#: pins both directions rather than only the collapsing one.
NEAR_THRESHOLD = 0.6

#: Words that carry no identity. Kept SHORT on purpose: an aggressive stop list
#: makes short entries collapse into each other, and short entries are exactly
#: where a false merge is most likely to hide something the wearer said.
_STOP = frozenset((
    "a", "an", "the", "to", "of", "and", "or", "i", "im", "ill", "id", "my",
    "me", "we", "is", "it", "that", "this", "for", "on", "at", "in", "with",
    "gotta", "need", "gonna", "have", "has", "be", "will", "would", "should",
))

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> frozenset:
    """The identity-bearing words of an entry, lowercased and de-stopped.

    Apostrophes are stripped BEFORE splitting, not treated as separators: on a
    word boundary `I'll` becomes `i` + `ll`, and `ll` is a token that appears in
    every sentence containing a contraction — so "I'll be at the shop" and
    "I'll be at the park" would share it and drift toward each other for a
    reason that has nothing to do with what the wearer said.

    A single LETTER is dropped as noise; a single DIGIT is not. "moment 0" and
    "moment 1" are different moments, "call at 5" and "call at 9" are different
    commitments, and a length filter that cannot tell those apart merges them
    silently \u2014 which is the worst failure this module has, because the merged
    entry looks perfectly reasonable and the other one is simply gone.
    """
    flat = (text or "").lower().replace("'", "").replace("\u2019", "")
    return frozenset(w for w in _WORD.findall(flat)
                     if w not in _STOP and (len(w) > 1 or w.isdigit()))


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of the two token sets, 0.0-1.0.

    Two entries with no identity-bearing words left are NOT similar — they are
    both empty, which is not the same as being the same. Returning 1.0 there
    would collapse every contentless entry into one.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def collapse(rows: Sequence, text_of: Callable, *,
             threshold: float = NEAR_THRESHOLD,
             newest_first: bool = True) -> list:
    """`[(row, repeats), …]` with near-duplicates merged into the row KEPT.

    The kept row is the one that appears first in `rows`, so a caller that hands
    them over newest-first keeps the most recent phrasing — which is the one the
    wearer said most recently and the one they will recognise.

    `repeats` counts the entries that folded in, INCLUDING the kept one, so a
    unique entry reports 1 rather than 0. A caller showing "×3" wants the total,
    and a `repeats` that meant "others" would be off by one at every call site.

    Order is otherwise preserved. Nothing is dropped that was not merged, and a
    row whose text is empty never merges with another empty one.
    """
    kept: list = []
    counts: list = []
    texts: list = []
    for row in rows or ():
        try:
            text = str(text_of(row) or "")
        except Exception:                            # noqa: BLE001
            text = ""
        hit = None
        if text.strip():
            for i, prior in enumerate(texts):
                if similarity(prior, text) >= threshold:
                    hit = i
                    break
        if hit is None:
            kept.append(row)
            counts.append(1)
            texts.append(text)
        else:
            counts[hit] += 1
    out = list(zip(kept, counts))
    return out if newest_first else out[::-1]


def decayed(rows: Sequence, ts_of: Callable, now: float, *,
            half_life_s: float = 7 * 86400.0,
            floor: float = 0.15) -> list:
    """`[(row, weight), …]` with weight falling by half every `half_life_s`.

    Staleness as a WEIGHT rather than a cutoff, deliberately: a hard age limit
    deletes the wearer's older memories from a view they did not ask to have
    filtered, while a weight lets a ranker prefer the recent without anything
    disappearing. `floor` keeps an old-but-real memory above zero so it can
    still be reached when nothing newer matches.

    An unreadable timestamp weighs `floor` — the same rule retention uses for an
    unreadable `created_at`: do not guess, and do not throw it away either.
    """
    out = []
    for row in rows or ():
        try:
            age = max(0.0, float(now) - float(ts_of(row)))
            w = 0.5 ** (age / half_life_s) if half_life_s > 0 else 1.0
        except Exception:                            # noqa: BLE001
            w = floor
        out.append((row, max(floor, min(1.0, w))))
    return out
