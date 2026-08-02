"""The bar your own swats set — `persona_tuning`, Brain-side.

WHY THIS EXISTS, AND WHY IT IS NOT IN `orchestrator/`
-----------------------------------------------------
`persona_tuning` had a tuner (`orchestrator/persona_humanlearn.tune`) and one
consumer: `MaturityGate.tuned_confidence`. `MaturityGate` is constructed at
exactly one site — `orchestrator/orchestrator.py` — and `decisions/0001` records
that the shipped Brain never builds an `Orchestrator`, with
`test_the_orchestrator_is_still_not_resurrected` keeping it that way. So the
tuner was reachable from tests and from the simulator, and from nothing the
wearer runs.

This follows the precedent that decision set rather than repeating the mistake:
`retention_live.py` did not resurrect the Orchestrator to get `RetentionSweep`
running, it re-hosted the plain part Brain-side. `tune()` is likewise a plain
function over labelled rows — nothing about it is Orchestrator-shaped. What was
Orchestrator-shaped was `MaturityGate`'s NOVICE/APPRENTICE/RESIDENT ladder,
which keys on a pairing date and an event count the Brain does not track. That
ladder stays where it is; the tuning does not need it.

WHAT IT ACTUALLY DOES
---------------------
Before this, `Brain.push_event` had no attention gate beyond five booleans:
no rate limit, no daily cap, and no confidence bar. A card fired at full rate
from the first minute, and the wearer's only recourse was switching a whole cue
kind off.

The gate learns one number from the wearer's own behaviour: **how sure must a
proactive card be before it is worth interrupting for?** The rule is written
out below in four lines, on purpose — that is the entire argument for
human-learn over a model. The human writes the shape; the wearer's swats choose
the threshold; the answer stays a sentence you can say out loud.

    "Show it if it is at least 80% sure."

IT CANNOT RUN AWAY, AND THAT FALLS OUT OF THE DESIGN
----------------------------------------------------
The obvious objection to a self-tightening gate is that suppression destroys
its own evidence: once the bar is at 0.80, nothing below 0.80 is ever shown, so
no label below 0.80 is ever collected, so the bar can never come back down.

That does not happen here, and it is worth being precise about why rather than
asserting it. The bar is refit from a ROLLING log. As suppression takes hold,
the surviving cards are all above the bar and are mostly kept — so the log
drifts toward a single label, `tune()` REFUSES on `len(set(labels)) < 2`, and
`bar()` returns 0.0. Cards flow again, both labels reappear, and a bar re-forms
only if the wearer's swats still justify one. The mechanism unlatches itself.
`test_attention_gate.py::TestItCannotRunAway` pins exactly this.

THE FLOOR
---------
With no history the bar is 0.0 and nothing is suppressed — byte-identical to
the behaviour before this module existed. A card carrying no confidence at all
is never gated, because there is nothing to judge it by. And `allows()` fails
OPEN, matching `_may_interrupt` and opposite to the Veil: an unreadable
*preference* must not silence a smoke alarm, while an unreadable *posture* must
not leak.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Optional

log = logging.getLogger("dreamlayer.attention")

#: Below this many labelled cards there is no bar at all. A threshold chosen
#: from a handful of swats is a mood, not a preference.
MIN_LABELLED = 20

#: The rolling window. Bounded so the gate answers to recent behaviour, and
#: because this is what lets a stuck bar unlatch (see the module docstring).
LOG_MAX = 240

#: The values the bar may take. Coarse on purpose — the wearer's history is
#: tens of cards, and a grid finer than their evidence invents precision.
CONFIDENCE_GRID = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90)

#: The bar can never exceed this. Even a wearer who swats almost everything
#: must not be able to argue the system into total silence — at that point the
#: honest control is the cue switch they already have, not a bar of 0.99 that
#: makes the feature look broken.
BAR_CEILING = 0.90


def _above_confidence(rows, min_confidence: float = 0.80):
    """The rule, written out rather than learned — the whole point of the
    library. Module level and not a lambda so it stays picklable for the
    cross-validated path."""
    return [float(r.get("confidence") or 0.0) >= min_confidence for r in rows]


class AttentionGate:
    """The wearer's learned interruption bar, persisted beside the Brain."""

    def __init__(self, path=None, now_fn=time.time):
        self._path = path
        self._now = now_fn
        self._lock = threading.Lock()
        self._log: deque = deque(maxlen=LOG_MAX)
        #: None = not yet fit since the last label. A fit that REFUSED caches
        #: 0.0, so a refusal is not re-derived on every single push.
        self._bar: Optional[float] = None
        self._fitted = False          # did tune() ever genuinely return a bar
        self._load()

    # ---------------------------------------------------------------- state

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:                            # noqa: BLE001 — absent/corrupt
            return
        rows = raw.get("labelled") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            return
        # Validate on LOAD, not only on write: a hand-edited or planted file
        # must not put a non-number where a float is expected and take the
        # gate down on the first push. Same discipline as discoveries.json.
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                conf = float(r["confidence"])
            except (KeyError, TypeError, ValueError):
                continue
            self._log.append({"kind": str(r.get("kind") or "")[:40],
                              "confidence": conf,
                              "dismissed": bool(r.get("dismissed"))})

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.write_text(
                json.dumps({"labelled": list(self._log)}), encoding="utf-8")
        except Exception as exc:                     # noqa: BLE001
            log.debug("[attention] could not persist: %s", type(exc).__name__)

    # ------------------------------------------------------------ feedback

    def observe(self, kind: str, confidence, dismissed: bool) -> bool:
        """Record what the wearer did with one card. True if it became a label.

        A card with no confidence is not a label: there is no number to
        attribute the wearer's reaction to, and inventing one (0.0, or the
        mean) would teach the gate a threshold nobody's behaviour supports.
        """
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            return False
        if conf != conf:                             # NaN clears every bar
            return False
        with self._lock:
            self._log.append({"kind": str(kind or "")[:40], "confidence": conf,
                              "dismissed": bool(dismissed)})
            self._bar = None                         # a new label invalidates the fit
            self._save()
        return True

    # ----------------------------------------------------------------- fit

    def bar(self) -> float:
        """The learned confidence bar, or 0.0 when the history does not support
        one. Cached until the next label arrives — this is on the push path."""
        with self._lock:
            if self._bar is not None:
                return self._bar
            self._bar = self._fit()
            return self._bar

    def _fit(self) -> float:
        rows = list(self._log)
        if len(rows) < MIN_LABELLED:
            return 0.0
        # The label is KEPT, not dismissed: the rule predicts the cards worth
        # showing, so the tuned threshold IS the bar rather than its complement.
        labels = [not r["dismissed"] for r in rows]
        try:
            from ...orchestrator.persona_humanlearn import tune
            tuned = tune(_above_confidence, rows, labels,
                         {"min_confidence": list(CONFIDENCE_GRID)})
        except Exception as exc:                     # noqa: BLE001
            log.info("[attention] tuning unavailable: %s", type(exc).__name__)
            return 0.0
        if not tuned:
            # Refused — too few examples, or every card got the same reaction.
            # Both mean confidence does not explain this wearer's behaviour,
            # and a bar drawn anyway would be a coincidence with a number on it.
            return 0.0
        self._fitted = True
        bar = float(tuned.params.get("min_confidence") or 0.0)
        return max(0.0, min(BAR_CEILING, bar))

    # ---------------------------------------------------------------- gate

    def allows(self, kind: str, confidence) -> bool:
        """May a card of this confidence interrupt? Fails OPEN.

        `confidence is None` — a card that never carried one — is always
        allowed. The gate judges cards that state how sure they are; it does
        not penalise the ones that do not, because absence is not low.
        """
        try:
            if confidence is None:
                return True
            conf = float(confidence)
            if conf != conf:                         # NaN clears nothing; let it through
                return True
            bar = self.bar()
            if bar <= 0.0:
                return True
            return conf >= bar
        except Exception as exc:                     # noqa: BLE001
            log.debug("[attention] gate unreadable, allowing: %s",
                      type(exc).__name__)
            return True

    # -------------------------------------------------------------- report

    def summary(self) -> dict:
        with self._lock:
            rows = list(self._log)
        swatted = sum(1 for r in rows if r["dismissed"])
        return {"labelled": len(rows),
                "swatted": swatted,
                "bar": self.bar(),
                "fitted": self._fitted,
                "min_labelled": MIN_LABELLED}

    def tuning_live(self) -> bool:
        """True only once `tune()` has genuinely returned a bar from this
        wearer's own labels — what `DL_WIRED_PERSONA_TUNING` follows. Importable
        is not it; a refusal is not it either."""
        self.bar()                                   # force a fit if one is due
        return self._fitted and self.bar() > 0.0


def gate(brain):
    """The Brain's one gate, built on first use and held for the session."""
    got = getattr(brain, "_attention", None)
    if got is None:
        path = None
        try:
            path = brain.cfg_dir / "attention.json"
        except Exception:                            # noqa: BLE001
            pass
        got = AttentionGate(path)
        brain._attention = got
    return got
