"""spaCy commitment extraction — pull (person, action, deadline) tuples from a
line so CommitmentDriftEngine.nudge() gets reliable structure.

ADD-alongside: new module (commitment_drift.py untouched). Lazy-imports spaCy
(extras group `intelligence`); when absent it falls back to a lightweight
regex/keyword extractor, so the tuple surface is populated either way.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("dreamlayer.commitment_nlp")

try:
    import spacy  # type: ignore
    _HAS_SPACY = True
except ImportError:
    _HAS_SPACY = False

_DEADLINE = re.compile(
    r"\b(today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|next week|by \w+|in \d+ (?:min|minutes|hours?|days?))\b", re.I)


@dataclass
class Commitment:
    subject: Optional[str]
    action: str
    deadline: Optional[str]


class CommitmentNLP:
    available = _HAS_SPACY

    def __init__(self):
        self._nlp = None
        if _HAS_SPACY:
            try:
                self._nlp = spacy.load("en_core_web_sm")
            except Exception as exc:
                log.warning("[commitment_nlp] model load failed: %s; regex fallback", exc)
                self._nlp = None

    def extract(self, text: str) -> Optional[Commitment]:
        """(subject, action, deadline) — never less than the fallback alone (#557).

        The regex extractor runs FIRST and unconditionally, and its result is
        used to fill any field the spaCy path left empty. That is what makes the
        module docstring's promise true — "the tuple surface is populated either
        way" — and it was not:

            "Send Marcus the lease by Friday"
              spaCy installed  → Commitment(subject=None,     action='send', ...)
              spaCy absent     → Commitment(subject='Marcus', ...)

        `_spacy_extract` took the subject only from an NER `PERSON` entity, and
        `en_core_web_sm` finds no entity at all in that sentence except the date.
        An under-populated result is not an exception, so the `except` branch
        below never fired and the caller simply got `subject=None`. Installing
        the optional dependency made the answer strictly worse — the same shape
        as #551/#552/#553, and the reason it went unnoticed is the same: the
        capability meter reported the seam active throughout.

        The merge is deliberately a floor rather than a preference. Where the
        spaCy path has an answer it keeps it (`action` from the ROOT lemma is
        genuinely better than the regex path's whole-sentence echo); where it has
        none, the fallback's answer is strictly more than nothing.

        The fallback is consulted ONLY when a field is actually missing, rather
        than every time. That keeps the cheap path cheap, and it keeps
        `test_ner_spacy_real.py`'s non-vacuity guard meaningful: those tests spy
        on `_regex_extract` and assert it was never reached, which is how they
        prove the real parser produced the answer rather than the test passing by
        quietly falling back. A fully-populated spaCy result never touches it.
        """
        if self._nlp is None:
            return self._regex_extract(text)
        try:
            got = self._spacy_extract(text)
        except Exception as exc:
            log.warning("[commitment_nlp] parse failed: %s; regex fallback", exc)
            return self._regex_extract(text)
        if got is None:
            return self._regex_extract(text)
        if got.subject and got.action and got.deadline:
            return got                       # nothing missing — no floor needed
        fallback = self._regex_extract(text)
        if fallback is None:
            return got
        return Commitment(
            subject=got.subject or fallback.subject,
            action=got.action or fallback.action,
            deadline=got.deadline or fallback.deadline,
        )

    def _person(self, doc) -> Optional[str]:
        """Who the commitment is with, read from the parse spaCy already built.

        Three sources, because measured against `en_core_web_sm` each one is the
        only one that works on some ordinary input and wrong on others:

            "Send Marcus the lease by Friday"       ents: []            dative: Marcus
            "Remind Priya about the invoice ..."    ents: []            dobj:   Priya
            "Email Dana the contract on Monday"     ents: [Email Dana]  (none)
            "I told Dr. Sarah Chen I would call"    ents: [Sarah Chen]  dobj:   Chen
            "Sarah Chen promised to send the lease" ents: [Sarah Chen]  nsubj:  Chen

        So NER alone answers nothing on the first two and the WRONG thing on the
        third — it swallows the imperative verb into the name, and the giveaway
        is that the parser then makes the NAME the sentence ROOT ("Dana"/PROPN)
        because no verb was left. The dependency parse names the person directly
        on the others, but as a single token, truncating "Sarah Chen" to "Chen".

        Hence: take the dependency candidate, upgrade it to the NER span that
        CONTAINS it (recovering the full "Sarah Chen"), and when only NER has an
        answer, trim the span to start at the ROOT if the ROOT lies INSIDE it —
        which is exactly the absorbed-verb case and nothing else. Trimming on
        "the span starts at token 0" instead would be wrong: "Sarah Chen promised
        …" also starts at token 0 and is a whole name, and its ROOT ("promised")
        sits outside the span.
        """
        ents = [e for e in doc.ents if e.label_ == "PERSON"]
        root = next((t for t in doc if t.dep_ == "ROOT"), None)
        dep = next((t for t in doc
                    if t.pos_ == "PROPN"
                    and t.dep_ in ("dative", "dobj", "iobj", "nsubj")
                    and root is not None and t.head is root), None)
        if dep is not None:
            for e in ents:                       # the fuller name, when there is one
                if e.start <= dep.i < e.end:
                    return e.text
            return dep.text
        if ents:
            e = ents[0]
            if root is not None and e.start <= root.i < e.end and root.i > e.start:
                return doc[root.i:e.end].text    # the verb was absorbed — drop it
            return e.text
        return None

    def _spacy_extract(self, text) -> Optional[Commitment]:
        doc = self._nlp(text)
        subj = self._person(doc)
        root = next((t for t in doc if t.dep_ == "ROOT"), None)
        action = (root.lemma_ if root else text).strip()
        dl = next((e.text for e in doc.ents if e.label_ in ("DATE", "TIME")), None)
        if dl is None:
            m = _DEADLINE.search(text)
            dl = m.group(0) if m else None
        return Commitment(subj, action or text, dl)

    def _regex_extract(self, text) -> Optional[Commitment]:
        if not text.strip():
            return None
        m = _DEADLINE.search(text)
        deadline = m.group(0) if m else None
        # crude subject: first Capitalized token that isn't the sentence-initial
        # word (usually a verb like "Send"/"Remind") and isn't part of the deadline
        words = text.split()
        dl_text = (deadline or "").lower()
        subj = None
        for i, w in enumerate(words):
            if i == 0:
                continue
            if re.fullmatch(r"[A-Z][a-z]+", w) and w.lower() not in dl_text:
                subj = w
                break
        return Commitment(subj, text.strip(), deadline)
