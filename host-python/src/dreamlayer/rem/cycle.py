"""rem/cycle.py — the sleep cycle: replay, recombine, consolidate.

What sleep does for a brain — consolidate, prune, strengthen — is a
memory-ranking optimization pass, and REM is that pass made visible.

The mechanics, in order:

  1. Gather the day's events from the semantic ring buffer (plus open
     promises from the drift engine). Private/veiled events are excluded
     at the door — they are never dreamed, scored, or rendered.
  2. Score each event's *salience*: confidence, kind (promises dream
     loudest, people next, plain memories last), recency, and whether
     the event's words touch an open promise.
  3. Run N sweeps. Each sweep draws pairs of events — salience-weighted,
     biased toward pairs from *different hours* (recombination is the
     point) — and the poet weaves each pair into one dream phrase. The
     pair's palette weathers blend into the scene's light.
  4. Consolidate: every appearance in a dream is a vote to remember
     (+PROMOTE per appearance); low-salience events that never surfaced
     all night are let go (−DEMOTE). Deltas are bounded and merge into
     the RetrievalBias store, which retrieval ranking and the Horizon
     composer's luma boost both read.

Everything is deterministic under `seed` — the same day dreams the same
dreams — which is what makes the morning reel a trustworthy readout of
what the glasses decided to remember.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional

from .bias import RetrievalBias, event_key, BIAS_MAX
from .poet import DreamPoet

PROMOTE_PER_DREAM = 0.10     # each dream appearance is a vote to keep
DEMOTE_UNDREAMED = -0.20     # low-salience events the night ignored
DEMOTE_SALIENCE_FLOOR = 0.45 # only quiet memories below this are let go
PAIRS_PER_SWEEP = 4
MIN_EVENTS = 2

_KIND_WEIGHT = {"promise": 0.40, "task": 0.40, "person": 0.25}
_DEFAULT_KIND_WEIGHT = 0.10


@dataclass
class DreamScene:
    """One dream: two memories from different hours, rewoven."""
    phrase: str
    a_key: str
    b_key: str
    a_summary: str
    b_summary: str
    a_hour: int
    b_hour: int
    weather_blend: float      # 0.0 = a's hour dominates … 1.0 = b's


@dataclass
class DreamReel:
    """The night's output: the dreams, and what they decided."""
    night_seed: int
    scenes: list[DreamScene] = field(default_factory=list)
    deltas: dict[str, float] = field(default_factory=dict)
    dream_counts: dict[str, int] = field(default_factory=dict)
    promise_dreams: dict[str, int] = field(default_factory=dict)
    summaries: dict[str, str] = field(default_factory=dict)

    def apply_to(self, bias: RetrievalBias) -> RetrievalBias:
        bias.decay()
        bias.apply(self.deltas)
        return bias

    def report(self) -> str:
        lines = [f"REM night (seed {self.night_seed}): "
                 f"{len(self.scenes)} dreams"]
        for s in self.scenes:
            lines.append(f"  ◦ {s.phrase!r}   "
                         f"[{s.a_hour:02d}h × {s.b_hour:02d}h]")
        promoted = sorted((k for k, v in self.deltas.items() if v > 0),
                          key=lambda k: -self.deltas[k])
        demoted = [k for k, v in self.deltas.items() if v < 0]
        lines.append(f"  consolidated: {len(promoted)} promoted, "
                     f"{len(demoted)} let go")
        for key in promoted[:5]:
            lines.append(f"    ↑ {self.summaries.get(key, key)!r} "
                         f"(+{self.deltas[key]:.2f}, "
                         f"dreamed ×{self.dream_counts.get(key, 0)})")
        for key in demoted[:5]:
            lines.append(f"    ↓ {self.summaries.get(key, key)!r} "
                         f"({self.deltas[key]:.2f})")
        return "\n".join(lines)


@dataclass
class _Dreamable:
    key: str
    kind: str
    summary: str
    ts: float
    hour: int
    salience: float


def _is_private(event) -> bool:
    meta = getattr(event, "meta", None) or {}
    # no_dream: the wearer said "don't dream about that" — the memory stays
    # retrievable, but the night never touches it (the Veil gates capture;
    # this gates consolidation *aesthetics*).
    return bool(meta.get("private")) or bool(meta.get("no_dream")) or \
        getattr(event, "source", "") == "veiled"


class REMCycle:
    """One night of functional dreaming over the day's events.

    ring    : SemanticRingBuffer (the day)
    drift   : CommitmentDrift engine, optional (open promises)
    privacy : object with allow_capture() — if capture is disallowed at
              cycle time the cycle still runs (dreaming is offline) but
              only over events already lawfully stored.
    """

    def __init__(self, ring, drift=None, privacy=None,
                 seed: Optional[int] = None, now_fn=None) -> None:
        self._ring = ring
        self._drift = drift
        self._privacy = privacy
        self._now = now_fn or time.time
        self.seed = seed if seed is not None else int(self._now()) // 86400
        self._rng = random.Random(self.seed)
        self._poet = DreamPoet(self._rng)

    # ------------------------------------------------------------------

    def run(self, sweeps: int = 3) -> DreamReel:
        events = self._gather()
        reel = DreamReel(night_seed=self.seed)
        if len(events) < MIN_EVENTS:
            return reel

        for ev in events:
            reel.summaries[ev.key] = ev.summary

        for _ in range(max(1, sweeps)):
            for a, b in self._draw_pairs(events):
                phrase = self._poet.weave(a.summary, b.summary)
                blend = self._rng.random()
                reel.scenes.append(DreamScene(
                    phrase=phrase,
                    a_key=a.key, b_key=b.key,
                    a_summary=a.summary, b_summary=b.summary,
                    a_hour=a.hour, b_hour=b.hour,
                    weather_blend=round(blend, 3),
                ))
                for ev in (a, b):
                    reel.dream_counts[ev.key] = \
                        reel.dream_counts.get(ev.key, 0) + 1
                    if ev.kind in ("promise", "task"):
                        reel.promise_dreams[ev.key] = \
                            reel.promise_dreams.get(ev.key, 0) + 1

        # -- consolidation: dreams promote; silence demotes competitively.
        # An undreamed event is let go if it sits at or below the day's
        # median salience — forgetting is relative to how loud the day
        # was, the way sleep prunes against the whole day's trace.
        saliences = sorted(ev.salience for ev in events)
        median = saliences[len(saliences) // 2]
        for ev in events:
            count = reel.dream_counts.get(ev.key, 0)
            if count > 0:
                reel.deltas[ev.key] = min(BIAS_MAX,
                                          PROMOTE_PER_DREAM * count)
            elif ev.salience <= max(median, DEMOTE_SALIENCE_FLOOR):
                reel.deltas[ev.key] = DEMOTE_UNDREAMED
        return reel

    # ------------------------------------------------------------------

    def _gather(self) -> list[_Dreamable]:
        now = self._now()
        out: list[_Dreamable] = []
        seen: set[str] = set()

        for buffered in self._ring.since(0.0):
            ev = buffered.event
            if _is_private(ev):
                continue
            kind = getattr(ev, "kind", "") or "memory"
            summary = getattr(ev, "summary", "") or ""
            if not summary.strip():
                continue
            key = event_key(kind, summary)
            if key in seen:
                continue
            seen.add(key)
            conf = float(getattr(ev, "confidence", 0.5) or 0.5)
            hours_ago = max(0.0, (now - buffered.ts) / 3600.0)
            recency = max(0.0, 1.0 - hours_ago / 24.0)
            out.append(_Dreamable(
                key=key, kind=kind, summary=summary, ts=buffered.ts,
                hour=int((buffered.ts % 86400) // 3600),
                salience=conf
                + _KIND_WEIGHT.get(kind, _DEFAULT_KIND_WEIGHT)
                + 0.2 * recency,
            ))

        # open promises dream even if they've scrolled off the buffer
        if self._drift is not None:
            promise_words: set[str] = set()
            for rec in self._drift.all_records():
                ev = getattr(rec, "event", None)
                summary = getattr(ev, "summary", "") if ev else ""
                if not summary or (ev is not None and _is_private(ev)):
                    continue
                key = event_key("promise", summary)
                promise_words.update(w.lower() for w in summary.split()
                                     if len(w) > 3)
                if key in seen:
                    continue
                seen.add(key)
                ts = getattr(rec, "due_ts", None) or now
                out.append(_Dreamable(
                    key=key, kind="promise", summary=summary, ts=float(ts),
                    hour=int((float(ts) % 86400) // 3600),
                    salience=0.9,
                ))
            # events whose words touch an open promise dream louder
            if promise_words:
                for d in out:
                    if d.kind not in ("promise", "task") and \
                            promise_words & {w.lower()
                                             for w in d.summary.split()}:
                        d.salience += 0.25

        return out

    def _draw_pairs(self, events: list[_Dreamable]):
        """Salience-weighted pairs, biased toward cross-hour collisions."""
        weights = [max(0.05, e.salience) for e in events]
        pairs = []
        for _ in range(min(PAIRS_PER_SWEEP, len(events))):
            a = self._rng.choices(events, weights=weights, k=1)[0]
            # recombination bias: prefer partners from a different hour
            partners = [e for e in events
                        if e.key != a.key and e.hour != a.hour]
            if not partners:
                partners = [e for e in events if e.key != a.key]
            if not partners:
                break
            pw = [max(0.05, e.salience) for e in partners]
            b = self._rng.choices(partners, weights=pw, k=1)[0]
            pairs.append((a, b))
        return pairs
