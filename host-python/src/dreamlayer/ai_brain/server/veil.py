"""veil.py — one Veil gate, and one answer to each of its two questions.

The Veil asks two things, and they are not the same question:

    allow_capture()   may we KEEP what we perceive right now?
    allow_recall()    may we READ BACK what we already know?

**Capture fails closed. Recall is unrestricted.** That split is the whole of
this module, and both halves are deliberate.

WHY RECALL IS OPEN
------------------
Because incognito is about not KEEPING, not about going blind. It is
`memory.privacy.PrivacyGate`'s own reading — its `allow_recall` is blocked
only by an explicit pause, and its docstring says so in as many words:
*"Incognito stops keeping new memories, not recalling old ones — you can still
ask what you already know while incognito."* This Brain has no pause input at
all; every term of `incognito_now()` (LAN-only, quiet hours, a private zone) is
a capture posture. So there is nothing left that could block a read.

The alternative was live here until this module settled it. Twelve
hand-written gates disagreed: most tied recall to capture, `lucid_live` did
not, and both sides had argued their case in a docstring without knowing the
other existed (decisions/0009). Under the strict reading a wearer lost their
own memory every night — quiet hours is a nightly window, so "what did we
decide about the lease?" answered "I am not allowed to say" until morning.
That is the wearer's own recall being withheld from them by a shield meant to
protect them from everyone else.

WHY THAT IS SAFE, AND THE PART THAT IS EASY TO GET WRONG
--------------------------------------------------------
Opening recall is only safe while recall means READING. Two methods in
`lens_hosts` were gated on `allow_recall` and did not read at all:

  * `resume()`   — `stasis.replace_frame(fresh)` then `save_stasis()`
  * `quest_complete()` — `saga.complete()` pays XP, `_saga_profile_record()`
    writes badge unlocks

They were filed under recall because that is what the gate happened to offer.
While recall was closed, that was invisible: nothing could fire either way.
Open recall and both would persist a record of what the wearer did DURING a
veiled stretch — which is exactly what `allow_capture` exists to prevent. Both
now ask `allow_capture`, because they were never recall questions.

`test_veil_gate.py::TestNothingWritesWhileVeiled` holds that line behaviourally
— it drives the real methods against a veiled Brain and asserts the writes
never happen. Without it, the next action accidentally filed under recall
becomes a silent write-while-veiled, and nothing would notice.

`veil_scope.py` is the other half of the Veil and a different question again:
this module answers "may I?", that one answers "everything stops, now".
"""
from __future__ import annotations


class VeilGate:
    """The wearer's posture, as any lens needs to ask about it.

    Duck-types `memory.privacy.PrivacyGate` — `allow_capture()` /
    `allow_recall()` — because that is the protocol every lens, pipeline and
    plugin facade in the tree already takes.
    """

    __slots__ = ("_brain",)

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        """May we KEEP what we perceive right now?

        Fails CLOSED. An unreadable posture is a veiled one — a broken trust
        signal must never resolve to "record it". All twelve hand-written gates
        already agreed on this, and it stays exact.

        This is also the gate for anything that WRITES, whether or not it reads
        first. "Am I allowed to remember this?" and "am I allowed to change
        something?" are the same question to a wearer who has put the Veil up.
        """
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False

    def allow_recall(self) -> bool:
        """May we READ BACK what we already know? Always yes.

        Not a fail-open and not a stub. The Brain has no pause input, and a
        pause is the only thing `PrivacyGate` blocks recall on — so this is the
        honest mapping of a term that can never be set, and returning True is
        the answer rather than the absence of one.

        It stays a method, and every read still calls it, for two reasons: the
        `PrivacyGate` protocol is what every consumer already takes, and if a
        real pause is ever added Brain-side, THIS is the one place that has to
        learn about it.
        """
        return True
