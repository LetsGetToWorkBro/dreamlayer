"""Commitments parsed properly — `nlp`, Brain-side.

THE HIGHEST-IMPACT ENTRY IN THE CATALOGUE, AND IT WAS FILED AS "BY DESIGN"
--------------------------------------------------------------------------
`nlp` is scored impact 5 — the only 5 there is — and its own gain text says
what the wearer loses without it: *"baseline pulls names/promises with regex
that breaks on real sentences; this parses them properly."* Commitments are the
engine this product is built on, so a regex that mis-reads them is not a
cosmetic gap.

It sat under "unreachable BY DESIGN" because `capability_reachability.py`
matched the `orchestrator/` prefix in its seam string. That was a path rule, not
a judgement, and "Orchestrator-only" is exactly the reason seven other
capabilities were re-hosted Brain-side on 2026-08-02. The bucket has been split
since; this is the first of the nine it exposed.

WHAT THE BRAIN DOES TODAY, AND WHAT THIS ADDS
---------------------------------------------
`BrainLenses.ingest_utterance` runs `pipelines.ingest.extract_events`, the tier-1
regex/heuristic pass. It finds that a promise was made and roughly what about.
What it is bad at is the two fields that make a promise *actionable*:

    "Send Marcus the lease by Friday"
      who is it to?   the regex takes a capitalised token and often takes the
                      wrong one, or none
      when is it due? "by Friday" survives; "end of week", "before the standup"
                      and "tomorrow morning" do not

`CommitmentNLP.extract` answers both, and it already honours the floor this repo
holds every optional dependency to: the regex runs FIRST and unconditionally,
and spaCy only fills fields it left empty. So with spaCy absent this is
byte-identical to the behaviour it replaces, and with spaCy present it can only
ever add.

That property is why this is a sharpening pass over the existing events rather
than a second extractor: two extractors would disagree, and the disagreement
would surface as duplicate commitments the wearer has to reconcile.
"""
from __future__ import annotations

import logging

log = logging.getLogger("dreamlayer.nlp_live")

#: Event kinds that describe a promise. Only these are sharpened — a note or a
#: caption has no subject or deadline to find, and running a parser over every
#: utterance would spend the model on sentences with no commitment in them.
#:
#: `extract_events` emits two of these ("promise", "task"); "commitment" is the
#: kind other writers use for the same thing (`memory/chroma_store.py`,
#: `persona_tuning`) and is listed so a row arriving from one of those paths is
#: sharpened identically. Nothing beyond these three is a guess about kinds that
#: might exist — a dead member here would be a claim, not a safety margin.
COMMITMENT_KINDS = frozenset({"commitment", "promise", "task"})


class NLPLive:
    """The Brain's parser pass, built once and held for the session."""

    def __init__(self, brain):
        self.brain = brain
        self._nlp = None
        self._ner = None
        #: Fields the parser filled that the REGEX had left empty. This is the
        #: honest measure of the capability — not "spaCy is installed", not
        #: "the pass ran", but "it added something the baseline missed".
        self.fields_added = 0
        self.sharpened = 0

    def nlp(self):
        if self._nlp is None:
            from ...orchestrator.commitment_nlp import CommitmentNLP
            self._nlp = CommitmentNLP()
        return self._nlp

    def ner(self):
        if self._ner is None:
            from ...social_lens.ner_spacy import SpacyNER
            self._ner = SpacyNER()
        return self._ner

    # ---------------------------------------------------------- commitments

    def sharpen(self, text: str, kind: str, meta: dict) -> dict:
        """Fill `person` and `due` on one commitment event, if the parser can.

        Returns the meta to use — the SAME dict when nothing was added, so a
        caller can tell "unchanged" from "improved" without comparing fields.

        Only ever ADDS. A value the regex already found is never overwritten:
        the baseline is what has been in front of wearers, and a parser that
        silently replaced a correct answer with a different one would be a
        regression nobody could see.
        """
        if kind not in COMMITMENT_KINDS or not (text or "").strip():
            return meta
        try:
            got = self.nlp().extract(text)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[nlp] extract failed: %s", type(exc).__name__)
            return meta
        if got is None:
            return meta
        out = dict(meta or {})
        added = 0
        if not out.get("person") and getattr(got, "subject", None):
            out["person"] = str(got.subject)
            added += 1
        if not out.get("due") and getattr(got, "deadline", None):
            out["due"] = str(got.deadline)
            added += 1
        if not added:
            return meta
        self.fields_added += added
        self.sharpened += 1
        return out

    # ----------------------------------------------------------------- names

    def people(self, text: str) -> list:
        """Names in a line, spaCy-backed when installed.

        `SpacyNER` carries its own heuristic fallback, so this is never less
        than the regex path — the same floor the commitment pass holds.
        """
        try:
            return list(self.ner().people(text or "") or [])
        except Exception as exc:                     # noqa: BLE001
            log.warning("[nlp] ner failed: %s", type(exc).__name__)
            return []

    # ---------------------------------------------------------------- report

    def status(self) -> dict:
        return {"sharpened": self.sharpened,
                "fields_added": self.fields_added,
                "parser": bool(getattr(self._nlp, "available", False)),
                "live": self.live()}

    def live(self) -> bool:
        """True only once the parser has added a field the regex missed.

        Deliberately not `CommitmentNLP.available`. spaCy being importable says
        nothing about whether it helped, and on a sentence the regex already
        handles it correctly adds nothing at all — which is the fallback working,
        not the capability driving.
        """
        return self.fields_added > 0


def nlp_live(brain) -> NLPLive:
    got = getattr(brain, "_nlp_live", None)
    if got is None:
        got = NLPLive(brain)
        brain._nlp_live = got
    return got
