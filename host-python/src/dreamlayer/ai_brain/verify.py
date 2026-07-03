"""ai_brain/verify.py — turn a checkable claim into a verdict.

Veritas decides *what* is worth checking; this is *how* a claim gets checked
against knowledge. It asks a knowledge tier — your local model first, the cloud
tier only if you've opted in — a tightly-shaped verification question and parses
the reply into a verdict Veritas can act on.

Provider-agnostic and offline-testable: the caller passes `ask_fn` (the brain
router's `ask`, which already honours the cloud gate), so nothing here reaches
the network on its own. Returns None when no tier can answer, so Veritas falls
back to its offline self-contradiction pass alone.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# how a knowledge tier should answer, so the parse is unambiguous
VERIFY_PROMPT = (
    "You are a careful fact-checker. Judge the statement below against what is "
    "publicly, verifiably known. Reply on ONE line, in exactly this form:\n"
    "VERDICT: <SUPPORTED|DISPUTED|UNVERIFIED> — <one short reason>\n"
    "Use DISPUTED only when the statement is clearly, factually wrong. Use "
    "UNVERIFIED when you lack the information to judge. Add nothing else.\n\n"
    'Statement: "{claim}"'
)

# words a model might use, mapped to our three verdicts
_VERDICT_WORDS = {
    "supported": "supported", "support": "supported", "true": "supported",
    "correct": "supported", "accurate": "supported", "confirmed": "supported",
    "right": "supported", "verified": "supported",
    "disputed": "disputed", "dispute": "disputed", "false": "disputed",
    "incorrect": "disputed", "wrong": "disputed", "inaccurate": "disputed",
    "misleading": "disputed", "untrue": "disputed",
    "unverified": "unverified", "unknown": "unverified", "unclear": "unverified",
    "uncertain": "unverified", "insufficient": "unverified", "unsure": "unverified",
}

# hedging language → lower our confidence in the verdict
_HEDGES = ("might", "may be", "maybe", "possibly", "perhaps", "unclear",
           "not sure", "hard to say", "roughly", "approximately", "i think",
           "seems", "appears", "likely", "probably")

_LEAD = re.compile(r"\bverdict\b\s*[:\-]?\s*", re.IGNORECASE)
_WORD = re.compile(r"[a-z]+")


def parse_verdict(text: str) -> Optional[dict]:
    """Parse a tier's reply into {verdict, basis, confidence}, or None if it
    carries no recognizable verdict."""
    t = (text or "").strip()
    if not t:
        return None
    head = _LEAD.sub("", t, count=1)          # drop a leading "VERDICT:" if present
    verdict = None
    for w in _WORD.findall(head.lower()):
        if w in _VERDICT_WORDS:
            verdict = _VERDICT_WORDS[w]
            break
    if verdict is None:
        return None
    # basis: prefer the clause after an em/en dash or colon; else the whole line
    basis = head
    m = re.search(r"[—\-:]\s*(.+)", head)
    if m:
        basis = m.group(1)
    basis = basis.strip().strip('"').strip()
    if len(basis) > 120:
        basis = basis[:119] + "…"
    low = t.lower()
    if verdict == "unverified":
        conf = 0.3
    else:
        conf = 0.8
        if any(h in low for h in _HEDGES):
            conf = 0.55                       # a hedged verdict is a soft one
    return {"verdict": verdict, "basis": basis, "confidence": conf}


def verify_claim(claim: str, ask_fn: Callable[[str], object]) -> Optional[dict]:
    """Verify one claim via a knowledge tier. `ask_fn(query)` returns an Answer
    (with `.text`) or None — the brain router's `ask`, which tries your local
    model first and the cloud only when opted in. Returns a verdict dict or None."""
    claim = (claim or "").strip()
    if not claim:
        return None
    try:
        ans = ask_fn(VERIFY_PROMPT.format(claim=claim))
    except Exception:
        return None
    if ans is None:
        return None
    text = getattr(ans, "text", None)
    if text is None:                          # tolerate a plain-string ask_fn
        text = ans if isinstance(ans, str) else ""
    return parse_verdict(text)
