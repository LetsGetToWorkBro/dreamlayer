"""veil.py — one Veil gate, and one place the recall question is answered.

The Veil is the product's central claim, and Brain-side it had TWELVE
implementations: `_LensGate`, `_EarGate`, `_LookGate`, `_TruthGate`,
`_FaceGate`, `_VoiceGate`, `_IntroGate`, `_TrainGate`, two `_PostureGate`s and
two `_Gate`s. Every one of them was hand-written against `brain.incognito_now()`
and several carried a docstring promising it "mirrors" the others.

`allow_capture` really was identical in all twelve, so the duplication looked
harmless. `allow_recall` was not, and that is why this module exists.

THE DISAGREEMENT
----------------
Two sites answered "may I read back what I already know while veiled?"
differently, and BOTH argued their case in a docstring, and NEITHER knew about
the other:

  * `lens_hosts._LensGate` made recall the same predicate as capture, reasoning
    that `trace()` and `check()` read a timeline of what was said in front of
    the wearer, "which is exactly the kind of read the shield exists to stop".
    17 call sites.
  * `lucid_live._Gate` kept recall open, reasoning from
    `memory.privacy.PrivacyGate`, whose `allow_recall` is blocked ONLY by an
    explicit pause: *"Incognito stops keeping new memories, not recalling old
    ones — you can still ask what you already know while incognito."* The Brain
    has no pause input, so the honest mapping of that term is "never set".
    Reached through `lucid_recall.router`.

Both readings are defensible. What is not defensible is that the answer depends
on which lens a wearer happens to ask, that neither site knew it was diverging,
and that a third — `plugins/base._recall_ok` — treats a gate with no
`allow_recall` at all as permissive.

WHY `recall` HAS NO DEFAULT
---------------------------
It is keyword-only and required. A default would re-create the original bug the
first time somebody added a thirteenth gate without thinking about it: the
divergence did not come from carelessness, it came from two careful people
answering a question locally that nobody had written down globally. Making the
call site say which posture it takes is the whole point — it turns an accident
into a declaration, and `test_veil_gate.py` asserts every construction makes
one.

This module deliberately does NOT decide which reading is right. It preserves
each site's current behaviour exactly and makes the split legible so it can be
settled on purpose. See `decisions/0009-veil-recall-semantics.md`.

`veil_scope.py` is the other half of the Veil and a different question: this
module answers "may I?", that one answers "everything stops, now".
"""
from __future__ import annotations

#: Recall is blocked whenever capture is. The stricter reading, and what the
#: majority of the Brain does today: a veiled stretch is one where the Brain
#: neither keeps nor surfaces what was said in front of the wearer.
RECALL_FOLLOWS_CAPTURE = "follows-capture"

#: Recall stays open while veiled. `memory.privacy.PrivacyGate`'s reading:
#: incognito stops KEEPING, not asking. Blocked only by an explicit pause,
#: which this Brain has no input for.
RECALL_SURVIVES_INCOGNITO = "survives-incognito"

POSTURES = (RECALL_FOLLOWS_CAPTURE, RECALL_SURVIVES_INCOGNITO)


class VeilGate:
    """The wearer's posture, as one lens needs to ask about it.

    Duck-types `memory.privacy.PrivacyGate` — `allow_capture()` /
    `allow_recall()` — because that is the protocol every lens, pipeline and
    plugin facade in the tree already takes.
    """

    __slots__ = ("_brain", "_recall")

    def __init__(self, brain, *, recall: str):
        if recall not in POSTURES:
            # Fail loudly rather than picking one. A typo here would otherwise
            # choose a privacy posture silently, which is the failure mode this
            # whole module exists to remove.
            raise ValueError(
                f"recall must be one of {POSTURES!r}, got {recall!r}")
        self._brain = brain
        self._recall = recall

    def allow_capture(self) -> bool:
        """May we KEEP what we perceive right now?

        Fails CLOSED. An unreadable posture is a veiled one — a broken trust
        signal must never resolve to "record it". This was the one thing all
        twelve hand-written gates already agreed on, and it stays exact.
        """
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False

    def allow_recall(self) -> bool:
        """May we READ BACK what we already know?

        Which question this is depends on the posture the call site declared.
        Under `RECALL_SURVIVES_INCOGNITO` it is not a question at all — there is
        no pause input on this Brain, so nothing can block it, and returning
        True is a mapping rather than a fail-open.
        """
        if self._recall == RECALL_SURVIVES_INCOGNITO:
            return True
        return self.allow_capture()

    @property
    def recall_posture(self) -> str:
        """Which reading this gate takes — for a surface that wants to say so,
        and for the tests that assert the split stays declared."""
        return self._recall

    def __repr__(self) -> str:                       # pragma: no cover - debug
        return f"VeilGate(recall={self._recall!r})"
