"""commitment_drift.py — commitments as physics objects that bloom, crack,
and shatter based on *behavior and time*.

A commitment is a little object under two forces:

  time pressure   the clock pushes decay up toward the due date
  behavior        what you actually do pushes it back down — mentioning
                  it, working near it, or keeping it *heals* the object
                  toward bloom; abandoning it shatters it outright

Decay is a 0-1 float after both forces resolve:
  0.0 = brand new / plenty of time / freshly tended
  1.0 = past due with nothing done / shattered

State ladder (thresholds configurable via CommitmentDriftEngine constructor):
  blooming   decay < 0.20
  healthy    0.20 <= decay < 0.50
  drifting   0.50 <= decay < 0.75
  cracking   0.75 <= decay < 1.00
  shattered  decay >= 1.00

Behavior model
--------------
Every impulse of progress adds *heal credit* that subtracts from the time
decay, so a tended commitment blooms back down the ladder. Heal credit is
not permanent: it relaxes on a half-life (PROGRESS_HALFLIFE_S), so a
commitment you stop tending slides back under time pressure — momentum
bleeds, like a real physics object. Two terminal verbs override the
forces entirely: keep() blooms and pins it, break() shatters it.

Progress arrives two ways: explicitly (nudge/keep/break, e.g. from a phone
tap or a resolved rehearsal) and ambiently — tick() scans the memory
stream and any event that plainly refers to a commitment nudges it, so
simply living near the promise keeps it alive. Private events
(meta.private) are never observed.
"""
from __future__ import annotations
import re
import time
from dataclasses import dataclass
from ..memory.ring_buffer import SemanticRingBuffer
from ..pipelines.ingest import MemoryEvent


_STATES = ["blooming", "healthy", "drifting", "cracking", "shattered"]
_THRESHOLDS = [0.20, 0.50, 0.75, 1.00]  # upper bound for each state (shattered = >=1.0)

PROGRESS_HALFLIFE_S = 6 * 3600.0   # heal credit halves every 6 h of neglect
NUDGE_CREDIT = 0.22                # one deliberate impulse of progress
OBSERVE_CREDIT = 0.14              # one ambient mention from the stream

# words too common to prove a commitment was referenced
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "your", "you",
    "have", "will", "about", "them", "they", "then", "when", "what",
    "call", "send", "make", "meet", "back", "into", "over", "some",
})


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']{4,}", (text or "").lower())
            if w not in _STOPWORDS}


@dataclass
class DriftRecord:
    event: MemoryEvent
    created_ts: float
    due_ts: float | None
    decay: float = 0.0
    state: str = "blooming"
    surfaced: bool = False
    # behavior dimension
    progress: float = 0.0          # heal credit at last_impulse_ts
    last_impulse_ts: float = 0.0   # when that credit was laid down
    resolved: str | None = None    # None | "kept" | "broken"
    bloomed: bool = False          # a fresh keep/nudge to celebrate once

    def heal_credit(self, now: float) -> float:
        """Progress relaxes on a half-life — momentum bleeds with neglect."""
        if self.progress <= 0.0 or self.last_impulse_ts <= 0.0:
            return 0.0
        dt = max(0.0, now - self.last_impulse_ts)
        return self.progress * (0.5 ** (dt / PROGRESS_HALFLIFE_S))


def _classify(decay: float) -> str:
    if decay >= 1.00:
        return "shattered"
    for threshold, state in zip(_THRESHOLDS, _STATES):
        if decay < threshold:
            return state
    return "shattered"


def _parse_due(due_str: str | None, created_ts: float) -> float | None:
    """Very small due-date parser: understands 'Xh', 'Xd', 'tomorrow'."""
    if not due_str:
        return None
    s = due_str.lower().strip()
    if "tomorrow" in s:
        return created_ts + 86400
    import re
    m = re.search(r"(\d+)\s*h", s)
    if m:
        return created_ts + int(m.group(1)) * 3600
    m = re.search(r"(\d+)\s*d", s)
    if m:
        return created_ts + int(m.group(1)) * 86400
    return None


class CommitmentDriftEngine:
    """Track commitment ring events and update their decay scores."""

    _DEFAULT_LIFETIME_S = 48 * 3600  # 48 h fallback when no due date

    def __init__(
        self,
        ring: SemanticRingBuffer,
        *,
        lifetime_s: float = _DEFAULT_LIFETIME_S,
        alert_states: tuple[str, ...] = ("cracking", "shattered"),
    ):
        self.ring = ring
        self.lifetime_s = lifetime_s
        self.alert_states = alert_states
        self._records: dict[int, DriftRecord] = {}  # keyed by ring bucket id
        self._last_observe_ts: float = 0.0

    # -- behavior: the forces you apply on purpose -----------------------

    def _find(self, subject: str) -> DriftRecord | None:
        """The commitment a human subject refers to: a summary substring
        match, or the person the promise is owed to."""
        self._sync()
        s = (subject or "").strip().lower()
        if not s:
            return None
        for rec in self._records.values():
            summary = (rec.event.summary or "").lower()
            person = ((rec.event.meta or {}).get("person") or "").lower()
            if s in summary or (person and s == person):
                return rec
        return None

    def nudge(self, subject: str, credit: float = NUDGE_CREDIT,
              now: float | None = None) -> DriftRecord | None:
        """Record progress toward a commitment. It heals toward bloom."""
        now = now if now is not None else time.time()
        rec = self._find(subject)
        if rec is None or rec.resolved is not None:
            return None
        # carry forward any still-live credit, then add the new impulse
        rec.progress = min(1.0, rec.heal_credit(now) + credit)
        rec.last_impulse_ts = now
        rec.bloomed = True
        return rec

    def keep(self, subject: str, now: float | None = None) -> DriftRecord | None:
        """You did it. Bloom and pin."""
        now = now if now is not None else time.time()
        rec = self._find(subject)
        if rec is None:
            return None
        rec.resolved = "kept"
        rec.progress, rec.last_impulse_ts = 1.0, now
        rec.decay, rec.state, rec.bloomed = 0.0, "blooming", True
        return rec

    def break_(self, subject: str, now: float | None = None) -> DriftRecord | None:
        """You let it go. Shatter and pin."""
        rec = self._find(subject)
        if rec is None:
            return None
        rec.resolved = "broken"
        rec.decay, rec.state = 1.0, "shattered"
        return rec

    def _auto_observe(self, now: float) -> None:
        """Ambient behavior: events in the stream that plainly refer to a
        commitment nudge it. Living near a promise keeps it blooming."""
        try:
            recent = list(self.ring.since(self._last_observe_ts))
        except Exception:
            return
        active = [r for r in self._records.values() if r.resolved is None]
        for buffered in recent:
            self._last_observe_ts = max(self._last_observe_ts, buffered.ts)
            ev = buffered.event
            if getattr(ev, "kind", "") == "task":
                continue                      # the promise itself, not progress
            if (getattr(ev, "meta", None) or {}).get("private"):
                continue                      # private moments are never observed
            ev_words = _keywords(getattr(ev, "summary", ""))
            ev_person = ((ev.meta or {}).get("person") or "").lower() \
                if getattr(ev, "meta", None) else ""
            for rec in active:
                person = ((rec.event.meta or {}).get("person") or "").lower()
                refers = bool(ev_words & _keywords(rec.event.summary)) or (
                    person and person == ev_person)
                if refers:
                    rec.progress = min(1.0, rec.heal_credit(buffered.ts)
                                       + OBSERVE_CREDIT)
                    rec.last_impulse_ts = buffered.ts
                    rec.bloomed = True

    def _sync(self) -> None:
        """Pull any new commitment events from the ring into _records."""
        seen_ids = set()
        for bucket in self.ring.latest(kind="task", limit=200):
            bid = id(bucket)
            seen_ids.add(bid)
            if bid not in self._records:
                meta = bucket.event.meta or {}
                due_ts = _parse_due(meta.get("due"), bucket.ts)
                self._records[bid] = DriftRecord(
                    event=bucket.event,
                    created_ts=bucket.ts,
                    due_ts=due_ts,
                )
        # prune evicted buckets
        for gone in set(self._records) - seen_ids:
            del self._records[gone]

    def tick(self, now: float | None = None) -> list[DriftRecord]:
        """Recompute every commitment under both forces. Returns records
        that newly entered an alert state this tick."""
        now = now if now is not None else time.time()
        self._sync()
        self._auto_observe(now)
        alerts: list[DriftRecord] = []
        for rec in self._records.values():
            if rec.resolved == "broken":
                rec.decay, rec.state = 1.0, "shattered"
                continue
            if rec.resolved == "kept":
                rec.decay, rec.state = 0.0, "blooming"
                continue

            span = (max(rec.due_ts - rec.created_ts, 1.0)
                    if rec.due_ts is not None else self.lifetime_s)
            time_decay = min((now - rec.created_ts) / span, 1.0)
            # behavior counters time: heal credit subtracts from decay,
            # so a tended commitment blooms back down the ladder.
            rec.decay = max(0.0, time_decay - rec.heal_credit(now))
            prev_state = rec.state
            rec.state = _classify(rec.decay)
            # healing out of an alert state re-arms the alert, so a
            # commitment that cracks, gets tended, and cracks again is
            # surfaced each time it slips.
            if rec.state not in self.alert_states:
                rec.surfaced = False
            elif not rec.surfaced:
                rec.surfaced = True
                alerts.append(rec)
            if prev_state != rec.state:
                rec.bloomed = _STATES.index(rec.state) < _STATES.index(prev_state)
        return alerts

    def all_records(self) -> list[DriftRecord]:
        self._sync()
        return list(self._records.values())
