"""Phase 2 (A-): lucid_recall converged + wired.

The audit graded lucid_recall Architecture C+ ("three disjoint implementations
that never compose; nothing wires LucidRecall into the orchestrator; its
memory_index.get() contract is implemented nowhere") and Test Coverage C- ("the
FACE path, no-match, UNKNOWN fallback and mem0-present branch are all
untested"). The recall gate (Privacy) was already fixed. These tests cover the
now-real backend + composition + the orchestrator wiring.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.lucid_recall import (
    LucidRecall, RetrieverRecallIndex, QueryType,
)
from dreamlayer.orchestrator.orchestrator import Orchestrator


class FakeBridge:
    def __init__(self):
        self.cards = []
        self._h = None

    def on_event(self, fn):
        self._h = fn

    def send_raw(self, c):
        pass

    def send_card(self, c, event=None):
        self.cards.append((c, event))

    def send_command(self, c):
        pass

    def inject_event(self, n):
        pass


class _Retr:
    """Minimal Retriever.search stand-in: [(score, memory_dict)]."""
    def __init__(self, summary=""):
        self._s = summary

    def search(self, query, top_k=1, kind=None):
        return [(0.9, {"summary": self._s})] if self._s else []


class _Match:
    def __init__(self, name, cid="c1"):
        self.contact = type("C", (), {
            "name": name, "contact_id": cid,
            "context_line": lambda self: "met at the expo"})()
        self.confidence = 0.91


class _Social:
    def __init__(self, match=None):
        self._m = match

    def identify(self, frame):
        return type("R", (), {"match": self._m})()


# --- the memory_index.get() contract now has a real backend ------------------

def test_adapter_get_returns_top_summary():
    idx = RetrieverRecallIndex(_Retr("You met Sarah at the expo."))
    assert idx.get("what did we discuss") == "You met Sarah at the expo."
    assert RetrieverRecallIndex(_Retr("")).get("anything") == ""
    assert idx.get("") == ""


def test_adapter_prefers_mem0_when_present():
    class _Mem0:
        def search(self, q, limit=1):
            return [{"text": "mem0 says hi"}]
    idx = RetrieverRecallIndex(_Retr("core recall"), mem0=_Mem0())
    assert idx.get("q") == "mem0 says hi"

    class _BrokenMem0:
        def search(self, q, limit=1):
            raise RuntimeError("mem0 down")
    idx2 = RetrieverRecallIndex(_Retr("core recall"), mem0=_BrokenMem0())
    assert idx2.get("q") == "core recall"        # falls through on error


# --- FACE / FACT / UNKNOWN routing branches ----------------------------------

def test_face_match_returns_contact_card():
    lr = LucidRecall(social_lens=_Social(_Match("Sarah")),
                     memory_index=_Retr("unused"))
    r = lr.query("who is this", camera_frame=np.zeros((2, 2)))
    assert r.query_type == QueryType.FACE
    assert r.answer == "Sarah" and r.contact_name == "Sarah"


def test_face_no_match_is_honest():
    lr = LucidRecall(social_lens=_Social(None),
                     memory_index=RetrieverRecallIndex(_Retr("")))
    r = lr.query("who is this", camera_frame=np.zeros((2, 2)))
    assert r.query_type == QueryType.FACE
    assert "Not in your contacts" in r.answer and r.confidence == 0.0


def test_fact_query_hits_memory_via_adapter():
    lr = LucidRecall(memory_index=RetrieverRecallIndex(_Retr("Lease renews in March.")))
    r = lr.query("what did we discuss about the lease")
    assert r.query_type == QueryType.FACT
    assert r.answer == "Lease renews in March." and r.source == "memory"


def test_unknown_when_nothing_matches():
    lr = LucidRecall(memory_index=RetrieverRecallIndex(_Retr("")))
    r = lr.query("xyzzy plugh frobozz")
    assert r.query_type == QueryType.UNKNOWN and r.answer == "No result"


# --- classify_fn composition (DenseRouter plugs in here) ---------------------

def test_classify_fn_overrides_keyword_heuristic():
    idx = RetrieverRecallIndex(_Retr("routed by semantics"))
    # "who is this" is FACE by keyword; force FACT via the seam
    lr = LucidRecall(memory_index=idx, classify_fn=lambda t: QueryType.FACT)
    r = lr.query("who is this")
    assert r.query_type == QueryType.FACT and r.answer == "routed by semantics"


def test_classify_fn_abstain_falls_back_to_keyword():
    lr = LucidRecall(memory_index=RetrieverRecallIndex(_Retr("kw")),
                     classify_fn=lambda t: None)   # abstains -> keyword decides
    r = lr.query("what did we discuss")
    assert r.query_type == QueryType.FACT


# --- the wiring: the orchestrator exposes a live, gated lucid surface --------

def test_orchestrator_wires_lucid_and_query_is_gated():
    orc = Orchestrator(FakeBridge())
    # it is actually constructed and composed with the real collaborators
    assert isinstance(orc.lucid, LucidRecall)
    assert orc.lucid._social is orc.social
    assert isinstance(orc.lucid._memory, RetrieverRecallIndex)
    assert orc.lucid._privacy is orc.privacy
    # a query returns a HUD card dict
    card = orc.lucid_query("what did we discuss")
    assert card.get("type") == "LucidRecallCard"
    # recall-gated: a full pause veil silences the card (SECURITY)
    orc.privacy.pause()
    veiled = orc.lucid_query("what did we discuss")
    assert veiled["query_type"] == QueryType.UNKNOWN.value
    assert veiled["primary"] == "No result"
