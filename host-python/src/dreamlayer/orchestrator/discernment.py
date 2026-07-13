"""discernment.py — one read from three lenses.

The answer to "should Veritas fold into Truth Lens?" is *no — compose*. The three
lenses answer different questions and run on different inputs:

  Veritas       is what they *said* true / consistent?      (content — text/knowledge)
  Truth Lens    is *how* they said it credible?             (delivery — face/voice/NPU)
  history       have they done this *before* with you?      (the ledger)

Each stays a single-responsibility engine. This composer fuses their outputs into
one graded call, because the whole is far stronger than any part: a claim that is
*factually* disputed AND delivered *deceptively* AND fits a *pattern* is a very
different thing from any one of those alone — and, just as important, a false
claim delivered *sincerely* is an honest mistake, not a lie, and should read that
way.

Pure and deterministic. Veritas' `FactCheck` is required; the Truth Lens
`CredibilityVector` is optional (the live NPU pipeline is a device seam), and
`history` is a count of prior times this speaker set off Veritas with you.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# content verdict → base concern (before folding in confidence)
_CONTENT_CONCERN = {
    "self_contradiction": 0.85,
    "disputed":           0.80,
    "unverified":         0.20,
    "supported":          0.0,
    "":                   0.0,
}
_FIRING = ("disputed", "self_contradiction")


@dataclass
class Discernment:
    stance: str                 # trust | note | caution | flag
    headline: str               # one-line human read
    content: str                # the Veritas verdict
    delivery: str               # the Truth Lens label, or ""
    weight: float               # 0-1 combined concern
    corroboration: str          # compact tag for the HUD footer
    reasons: list[str] = field(default_factory=list)


def discern(fact, credibility=None, history: int = 0) -> Discernment:
    """Fuse a Veritas `FactCheck` with an optional Truth Lens `CredibilityVector`
    and a history count into one graded call."""
    verdict = getattr(fact, "verdict", "") or ""
    fconf = float(getattr(fact, "confidence", 0.0) or 0.0)
    content_fired = verdict in _FIRING
    content = _CONTENT_CONCERN.get(verdict, 0.0) * (fconf if fconf else 1.0)

    # delivery — only trust it once the read is calibrated enough
    delivery_label, delivery = "", 0.0
    deceptive = credible_delivery = False
    if credibility is not None and float(getattr(credibility, "confidence", 0.0) or 0.0) >= 0.3:
        delivery_label = getattr(credibility, "label", "") or ""
        dprob = float(getattr(credibility, "deception_prob", 0.0) or 0.0)
        delivery = dprob * float(credibility.confidence)
        deceptive = dprob >= 0.65
        credible_delivery = dprob < 0.40

    hist = min(max(0, history), 3) * 0.15         # a pattern adds weight, capped

    # content leads; delivery corroborates (half weight); a match is worth more
    weight = content + delivery * 0.5 + hist
    if content_fired and deceptive:
        weight += 0.2                              # both agree → synergy
    weight = round(min(1.0, weight), 3)

    reasons: list[str] = []
    if verdict:
        reasons.append(f"content: {verdict.replace('_', ' ')}")
    if delivery_label:
        reasons.append(f"delivery: {delivery_label.lower()}")
    if history >= 1:
        reasons.append(f"pattern: {history}× before")

    headline, corrob = _narrate(verdict, content_fired, deceptive,
                                credible_delivery, delivery_label, history)

    if weight >= 0.8:
        stance = "flag"
    elif weight >= 0.5:
        stance = "caution"
    elif weight >= 0.25:
        stance = "note"
    else:
        stance = "trust"

    return Discernment(stance=stance, headline=headline, content=verdict,
                       delivery=delivery_label, weight=weight,
                       corroboration=corrob, reasons=reasons)


def _narrate(verdict, content_fired, deceptive, credible_delivery,
             delivery_label, history):
    """The human sentence + the compact HUD tag for a (content, delivery) pair."""
    tags = []
    if delivery_label:
        tags.append(delivery_label.lower())
    if history >= 1:
        tags.append("seen before")
    corrob = " · ".join(tags)

    if content_fired and deceptive:
        return "Doesn't add up — and it didn't sound like it, either.", corrob
    if content_fired and credible_delivery:
        return "The claim is off, but they seem to mean it.", corrob
    if content_fired:
        base = ("They contradicted their earlier words."
                if verdict == "self_contradiction"
                else "That claim doesn't hold up.")
        if history >= 1:
            base += " Not the first time."
        return base, corrob
    if verdict == "supported" and deceptive:
        return "Checks out — but the delivery was uneasy.", corrob
    if verdict == "supported":
        return "Checks out.", corrob
    if verdict == "unverified":
        return "Couldn't verify that one.", corrob
    return "Nothing to flag.", corrob
