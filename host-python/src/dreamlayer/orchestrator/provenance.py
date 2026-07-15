"""provenance.py — Provenance Lens: where did that belief come from?

Truth Lens judges whether *other people* are credible. Candor keeps your
own story consistent. The Provenance Lens is the third of that family and
the strangest: point it at something you believe or are about to repeat,
and it traces the belief back through your own memory to its origin —

    "You believe the deadline is Friday because Maya told you, 3 weeks
     ago, unverified — and you also recorded Sam saying Thursday."

It answers three questions no other instrument does: *who* put this in your
head, *when*, and *how well is it stood up* — corroborated by independent
sources, or resting on a single piece of hearsay, or already contested by
something else you recorded.

Deterministic, offline, over the memory ring. It never asserts truth — only
genealogy and standing, so you can weigh a belief instead of just holding
it. Private memories (meta.private) are never traced; the orchestrator
gates the whole lens behind the Privacy Veil.

Memory hints it reads (all optional, from event.meta):
  person : who the memory is attributed to ("Maya")
  via    : how it entered — said/heard/read/saw/observed/recorded
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .consistency import ConsistencyEngine, _keywords, contradicts

# ways a belief can be firsthand — you were there for it
_FIRSTHAND_VIA = frozenset({"said", "saw", "observed", "did", "firsthand"})

_MONTH = 2_592_000.0
_WEEK = 604_800.0
_DAY = 86_400.0
_HOUR = 3_600.0
_MIN = 60.0


def humanize_age(seconds: float) -> str:
    s = max(0.0, seconds)
    if s < 90:
        return "just now"
    for span, unit in ((_MONTH, "month"), (_WEEK, "week"), (_DAY, "day"),
                       (_HOUR, "hour"), (_MIN, "minute")):
        if s >= span:
            n = int(s // span)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


@dataclass
class Source:
    """One memory that bears on the claim."""
    summary: str
    who: Optional[str]
    when_ts: float
    via: str
    confidence: float

    def attribution(self, now: float) -> str:
        who = self.who or "you"
        via = "" if self.via in ("recorded", "") else f" ({self.via})"
        return f"{who}{via}, {humanize_age(now - self.when_ts)}"


@dataclass
class ProvenanceResult:
    found: bool
    claim: str
    origin: Optional[Source]          # earliest supporting memory
    supports: list[Source] = field(default_factory=list)
    corroboration: int = 0            # count of independent attributions
    status: str = "unknown"           # unknown|unverified|corroborated|firsthand|contested
    contradiction: Optional[str] = None
    card: Optional[dict] = None


class ProvenanceLens:
    """Trace a belief to its origin and weigh how well it stands up."""

    def __init__(self, ring, *, lookback: int = 80, min_shared: int = 2,
                 min_confidence: float = 0.20):
        self.ring = ring
        self.lookback = lookback
        self.min_shared = min_shared
        self.min_confidence = min_confidence
        # reuse Candor to detect a contradicting prior
        self._candor = ConsistencyEngine(
            ring, lookback=lookback, min_shared=min_shared,
            min_prior_confidence=min_confidence)

    def trace(self, claim: str, now: Optional[float] = None) -> ProvenanceResult:
        import time
        now = now if now is not None else time.time()
        claim_keys = _keywords(claim)

        supports: list[Source] = []
        for b in self.ring.latest(limit=self.lookback):
            ev = b.event
            meta = getattr(ev, "meta", None) or {}
            if meta.get("private"):
                continue                       # never trace private memory
            if float(getattr(ev, "confidence", 0.0) or 0.0) < self.min_confidence:
                continue
            summary = getattr(ev, "summary", "") or ""
            if len(claim_keys & _keywords(summary)) < self.min_shared:
                continue
            if contradicts(claim, summary, self.min_shared) is not None:
                continue                       # a clashing memory isn't support
            supports.append(Source(
                summary=summary, who=meta.get("person"), when_ts=b.ts,
                via=(meta.get("via") or "recorded"),
                confidence=float(getattr(ev, "confidence", 0.0) or 0.0)))

        if not supports:
            return ProvenanceResult(found=False, claim=claim, origin=None)

        # a contradicting prior makes the belief contested (Candor)
        clash = self._candor.check(claim, now=now)
        contradiction = clash.prior_summary if clash.fired else None

        origin = min(supports, key=lambda s: s.when_ts)
        # independent attributions: distinct people, or distinct via+day
        attributions = set()
        firsthand = False
        for s in supports:
            if s.via in _FIRSTHAND_VIA:
                firsthand = True
            key = s.who or f"{s.via}:{int(s.when_ts // _DAY)}"
            attributions.add(key)
        corroboration = len(attributions)

        if contradiction:
            status = "contested"
        elif firsthand:
            status = "firsthand"
        elif corroboration >= 2:
            status = "corroborated"
        else:
            status = "unverified"

        result = ProvenanceResult(
            found=True, claim=claim, origin=origin, supports=supports,
            corroboration=corroboration, status=status,
            contradiction=contradiction)
        result.card = self._card(result, now)
        return result

    def _card(self, r: ProvenanceResult, now: float) -> dict:
        # _card is only built for a found result (trace() returns early with no
        # card when origin is None), so the origin is always present here.
        assert r.origin is not None
        status_color = {
            "firsthand": "accent_success", "corroborated": "accent_success",
            "unverified": "accent_attention", "contested": "accent_error",
        }.get(r.status, "text_secondary")
        lines = ["PROVENANCE", r.claim,
                 f"from {r.origin.attribution(now)}", r.status.upper()]
        if r.corroboration >= 2:
            lines.append(f"{r.corroboration} sources")
        if r.contradiction:
            lines.append(f"but also: {r.contradiction}")
        return {
            "type": "ProvenanceCard",
            "dismiss_ms": 6000,
            "eyebrow": "PROVENANCE",
            "primary": r.claim,
            "detail": f"from {r.origin.attribution(now)}",
            "footer": r.status,
            "status": r.status,
            "corroboration": r.corroboration,
            "contradiction": r.contradiction,
            "color": status_color,
            "lines": lines,
        }
