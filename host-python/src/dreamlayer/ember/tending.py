"""ember/tending.py — the night offers; the wearer chooses; nothing else keeps.

After REM runs (rem/nightly.py), this pass looks over the same day and stages
at most a handful of moments as *offers* for the morning ritual on the phone:
"which of these do you want to carry yourself?" The night's dream verdicts
feed the ranking — a moment the glasses dreamed about repeatedly is a moment
the day itself flagged — but the choice is never automatic. Zero candidates
becoming engrams is a perfectly good morning.

Privacy: the ring only ever holds lawfully-captured events (the Veil gates
ingest upstream), and this pass additionally refuses anything marked
meta.private / meta.no_dream / source=="veiled" — same door policy as the
REM cycle. What the wearer said not to dream about is also not offered for
keeping; a tending card quoting it would be the ambush Ember exists to avoid.

Cue generation is deliberately tier-1 here (regex + templates, offline,
deterministic): the cue must *point at* the moment without *containing* it.
A connected Mac Brain can regenerate richer cues later through the same
store; the contract — cue never equals answer — is enforced either way.
"""
from __future__ import annotations

import re
import time

from ..rem.bias import event_key
from .engram import TendingCandidate

MAX_CANDIDATES = 9        # the phone shows at most this many offers…
MAX_KEEPS_PER_DAY = 3     # …and the ritual accepts at most this many keeps
MIN_SALIENCE = 0.35       # below this a moment isn't worth interrupting coffee
DREAM_BOOST = 0.15        # per REM dream appearance (capped at 3)

_KIND_WEIGHT = {"promise": 0.30, "person": 0.25, "conversation": 0.20}
_DEFAULT_KIND_WEIGHT = 0.10

_SAID = re.compile(
    r"^\s*([A-Z][\w'.-]*)\s+(said|told|asked|mentioned|explained|promised)\b",
    re.IGNORECASE)
_STOP = frozenset("the a an my your our his her their this that it i we you"
                  .split())


def _is_private(event) -> bool:
    meta = getattr(event, "meta", None) or {}
    return bool(meta.get("private")) or bool(meta.get("no_dream")) or \
        getattr(event, "source", "") == "veiled"


def make_cue(kind: str, summary: str) -> str:
    """A prompt that reaches toward the moment without handing it over.

    Templates, cheapest first:
      "Maya said …"        → "What did Maya say?"
      promise/task         → "What did you promise?"
      person               → "Who was it — and what mattered?"
      anything else        → "About <lead words>… — what happened?"

    The guarantee callers rely on: the cue never contains the whole summary
    (asserted by tests; the reveal card is the only place the answer shows).
    """
    s = (summary or "").strip()
    m = _SAID.match(s)
    if m:
        verb = m.group(2).lower()
        asked = {"asked": "ask", "promised": "promise"}.get(verb, "say")
        return f"What did {m.group(1)} {asked}?"
    if kind in ("promise", "task"):
        return "What did you promise?"
    if kind == "person":
        return "Who was it — and what mattered?"
    words = [w for w in s.split() if w.lower() not in _STOP]
    lead = " ".join(words[:3]) if words else " ".join(s.split()[:3])
    return f"About {lead}… — what happened?" if lead else "What happened here?"


class TendingPass:
    """Stage the day's offers into the store. Deterministic given (ring,
    reel, now) — like the REM cycle, a re-run of an interrupted morning
    stages the same offers."""

    def __init__(self, store, privacy=None, now_fn=None,
                 max_candidates: int = MAX_CANDIDATES):
        self._store = store
        self._privacy = privacy
        self._now = now_fn or time.time
        self._max = max(1, int(max_candidates))

    def gather(self, ring, reel=None, now: float | None = None) -> list[TendingCandidate]:
        """Rank the day and return the offers (unstaged). Pure read."""
        now = self._now() if now is None else now
        dream_counts = getattr(reel, "dream_counts", None) or {}
        night_seed = int(getattr(reel, "night_seed", 0) or 0)

        seen: set[str] = set()
        out: list[TendingCandidate] = []
        for buffered in ring.since(0.0):
            ev = buffered.event
            if _is_private(ev):
                continue
            summary = (getattr(ev, "summary", "") or "").strip()
            if not summary:
                continue
            kind = getattr(ev, "kind", "") or "memory"
            key = event_key(kind, summary)
            if key in seen:
                continue
            seen.add(key)
            conf = float(getattr(ev, "confidence", 0.5) or 0.5)
            hours_ago = max(0.0, (now - buffered.ts) / 3600.0)
            recency = max(0.0, 1.0 - hours_ago / 24.0)
            salience = (conf
                        + _KIND_WEIGHT.get(kind, _DEFAULT_KIND_WEIGHT)
                        + 0.2 * recency
                        + DREAM_BOOST * min(3, dream_counts.get(key, 0)))
            if salience < MIN_SALIENCE:
                continue
            meta = getattr(ev, "meta", None) or {}
            out.append(TendingCandidate(
                id=0, kind=kind, summary=summary,
                cue=make_cue(kind, summary),
                salience=round(salience, 3),
                place_signature=str(meta.get("place_signature", "") or ""),
                source_memory_id=int(getattr(ev, "db_id", 0) or 0),
                night_seed=night_seed,
            ))
        out.sort(key=lambda c: (-c.salience, c.summary))
        return out[:self._max]

    def run(self, ring, reel=None, now: float | None = None) -> list[TendingCandidate]:
        """Gather and stage into the store; returns what was staged."""
        now = self._now() if now is None else now
        offers = self.gather(ring, reel=reel, now=now)
        self._store.add_candidates(offers, now)
        return self._store.candidates()
