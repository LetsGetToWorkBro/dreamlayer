"""LLM intent parser — an OPTIONAL *suggestion layer above the closed grammar*,
never inside it. A NEW sibling class (intent_parser.py is untouched).

Design principle (see docs/adr and INNOVATION_SESSION 5.4 / Category 8 #4). The
reality compiler's safety story is that behaviors are *data*, statically
budget-verified before they run. A non-deterministic model must never sit
*inside* that proof path. So this class is deliberately arranged so it cannot
weaken it:

  * **Deterministic by default.** With no model wired (the default today) it
    *is* the regex `IntentParser`, byte-for-byte.
  * **The model only suggests; the deterministic matcher decides.** When an
    `llm` is injected, its free-form output is folded back through the same
    regex matchers, so the return value is *always* a schema-legal
    `BehaviorIntent` — the model can nudge phrasing toward the closed grammar,
    it cannot invent a behavior outside it.
  * **It doesn't deploy.** Whatever it returns still passes `budgets.verify()`
    downstream before anything reaches glass. The proof, not the parser, is the
    gate.

So it's a convenience for turning messy speech into a *candidate* intent, with
zero authority over safety. Not "regex in a trenchcoat" — an honest front-end
that is structurally forbidden from being anything more.

    p = LLMIntentParser()                 # deterministic until a model + dep are wired
    intent = p.parse("round timer 3 minutes")
"""
from __future__ import annotations
import logging

from .intent_parser import IntentParser
from .schema import BehaviorIntent

log = logging.getLogger("dreamlayer.intent_parser_llm")


class LLMIntentParser:
    """Structured NL→BehaviorIntent with a guaranteed regex fallback.

    Parameters
    ----------
    llm : callable | None
        Optional `llm(prompt:str)->str` returning a restatement in the closed
        grammar. Absent → the regex parser, byte for byte.
    """

    def __init__(self, llm=None):
        self._regex = IntentParser()
        self._llm = llm

    def parse(self, text: str) -> BehaviorIntent:
        """Messy speech → a schema-legal BehaviorIntent, or ValueError.

        The model path runs whenever a model is wired, and requires nothing
        else. It used to be gated on instructor/outlines, which this module has
        never called: a wearer who had wired a local model got the bare regex
        parser until they installed two libraries that do nothing here. The
        import probes that backed that gate are gone too — the capability
        catalogue names the extras, and a module holding a second copy of that
        claim is a second thing that can be wrong.
        """
        if self._llm is None:
            return self._regex.parse(text)
        try:
            return self._llm_parse(text)
        except ValueError:
            # "Not one of the 15" — the ORDINARY outcome, not a failure. It is
            # already the deterministic parser's own verdict on both the
            # restatement and the raw text, so re-running it here would just
            # raise the same error a second time. Re-raised untouched: the caller
            # (`rc_compose`) turns it into the worked-examples reply.
            #
            # Deliberately NOT logged. The old handler caught this alongside real
            # errors and logged `exc`, whose message embeds the text verbatim —
            # and the text is the wearer's own description of a lens they want.
            # The logging-discipline rule is that captured content is drawn,
            # never logged.
            raise
        except Exception as exc:  # a genuine suggester/transport fault
            log.warning("[intent_parser_llm] suggester failed: %s; regex",
                        type(exc).__name__)
            return self._regex.parse(text)

    def _llm_parse(self, text: str) -> BehaviorIntent:
        """Ask the model to restate the request in the closed grammar, then let
        the deterministic matchers decide — so the return value is always a
        schema-legal `BehaviorIntent` no matter what the model said.

        THE RESTATEMENT IS PARSED FIRST, ALONE. This used to concatenate —
        `self._regex.parse(f"{text} {hint}")` — which let the original phrasing's
        noise outvote the model's restatement, because the matchers run in a
        fixed order and the first one to match wins. Measured:

            "I want to keep score during the match, tap to add a point"
              model restates    → "points marker"
              concatenated      → SimpleCounterIntent   (the raw text won)
              restatement alone → PointsMarkerIntent    (correct)

        So the optional model, once wired, produced the same answer the regex
        gave on its own — its entire contribution erased by the concatenation.

        Falling back to the raw text when the restatement does not parse is what
        makes this a FLOOR rather than a gamble: the model can only add a reading
        the regex could not reach, never take one away. Both failing raises, which
        is exactly what the regex-only path does today.
        """
        hint = (self._llm(text) or "").strip()
        if hint:
            try:
                return self._regex.parse(hint)
            except ValueError:
                # The model answered something outside the grammar. Not an error
                # worth surfacing — it is the ordinary case for a small local
                # model, and the wearer's own words are still there to try.
                log.debug("[intent_parser_llm] restatement did not parse; raw text")
        return self._regex.parse(text)
