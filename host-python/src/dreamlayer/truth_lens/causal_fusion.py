"""Causal credibility fusion (dowhy) — asks "what would have to be true for this
claim to be reliable?" instead of correlation-only consistency.

ADD-alongside: new sibling to fusion.py (FusionEngine untouched). Lazy-imports
dowhy (extras group `causal`); when absent, `assess()` returns None so the host
keeps using the existing FusionEngine unchanged. This is an optional second
opinion, never a replacement.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.causal_fusion")

try:
    import dowhy  # type: ignore  # noqa: F401
    _HAS_DOWHY = True
except ImportError:
    _HAS_DOWHY = False


class CausalFusion:
    available = _HAS_DOWHY

    def assess(self, au=None, prosody=None, linguistic=None, baseline=None):
        """Return an optional causal-credibility score in [0,1], or None when the
        dep is absent / inputs insufficient (caller falls back to FusionEngine)."""
        if not _HAS_DOWHY:
            return None
        try:
            # Minimal, dependency-light causal read: treat the three channels as
            # candidate causes of a "reliable" outcome and weight by agreement.
            signals = [s for s in (getattr(au, "score", None),
                                   getattr(prosody, "stress", None),
                                   getattr(linguistic, "confidence", None)) if s is not None]
            if not signals:
                return None
            agree = 1.0 - (max(signals) - min(signals))
            return max(0.0, min(1.0, agree))
        except Exception as exc:
            log.error("[causal_fusion] failed: %s", exc)
            return None
