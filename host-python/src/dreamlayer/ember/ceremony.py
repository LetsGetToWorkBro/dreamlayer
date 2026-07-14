"""ember/ceremony.py — the deletion ceremony: the machine makes itself
unnecessary, and proves it.

When an engram graduates (scheduler.py raised the flag), its recording
becomes a standing *offer*, never an automatic act: `offers()` lists what may
burn; `burn()` burns exactly one, and only with `consent=True` passed
explicitly by the surface the wearer tapped. There is no burn_all and no
default — the whole feature is an argument about agency, and the ceremony is
where the argument has to be airtight.

What a burn actually does, in order:
  1. purge the source memory through memory.retrieval.Retriever.purge_memory
     — the row AND its ANN vector (a bare db.purge leaves the moment
     recallable by similarity; see the warning in memory/privacy.py),
  2. blank the engram's answer and mark it burned (store.mark_burned),
  3. optionally plant a *tombstone*: a pinned memory holding only the cue,
     so the anniversary Ember lens (ops_world_lenses.ember) can, a year on,
     show "you kept: 'What did Dad say about the ice?'" — and the wearer
     answers it from the only place it still exists.

The receipt returned is the demo, the log line, and the trust artifact: what
burned, when, and what remains.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engram import Engram
from .store import EmberStore

TOMBSTONE_KIND = "ember"


@dataclass(frozen=True)
class BurnReceipt:
    engram_id: int
    cue: str
    burned_at: float
    purged_memory_id: int      # 0 = there was no warm-store row to purge
    tombstone_memory_id: int   # 0 = no tombstone requested/possible
    reps: int                  # how many recalls earned this


def offers(store: EmberStore) -> list[Engram]:
    """Graduated, unburned: every recording the wearer has earned the right
    to be rid of. Pure read; presenting these is the phone's job."""
    return store.graduated_unburned()


def burn(store: EmberStore, engram_id: int, *, consent: bool,
         now: float, retriever=None, db=None) -> BurnReceipt:
    """Burn one graduated engram's recording. Raises rather than guesses:

      consent is not True      → ValueError (no surface may default it)
      unknown / already burned → ValueError
      not graduated            → ValueError (the offer was never earned)
    """
    if consent is not True:
        raise ValueError("a burn requires explicit consent=True")
    e = store.get(engram_id)
    if e is None or e.burned:
        raise ValueError(f"no burnable engram {engram_id}")
    if not e.state.graduated:
        raise ValueError(f"engram {engram_id} has not graduated")

    purged = 0
    if e.source_memory_id and retriever is not None:
        # ANN-safe purge — row and vector together, or it isn't forgetting
        retriever.purge_memory(e.source_memory_id)
        purged = e.source_memory_id

    tombstone = 0
    if db is not None:
        # cue only — the answer's absence from disk is the entire point
        tombstone = db.add_memory(
            kind=TOMBSTONE_KIND, summary=e.cue, confidence=1.0,
            meta={"pinned": True, "ember_tombstone": True,
                  "kept_at": e.kept_at, "reps": e.state.reps})

    store.mark_burned(engram_id, now)
    return BurnReceipt(engram_id=e.id, cue=e.cue, burned_at=now,
                       purged_memory_id=purged,
                       tombstone_memory_id=tombstone, reps=e.state.reps)
