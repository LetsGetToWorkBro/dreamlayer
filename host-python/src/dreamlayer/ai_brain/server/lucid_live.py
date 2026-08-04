"""LucidRecall, Brain-side — one question, routed to the face or the memory.

`lucid_recall/router.LucidRecall` decides whether "who is this?" wants the
camera and "what did we say about the lease?" wants the memory store, and
returns one `LucidRecallResult` either way. It has never been constructed by
anything the wearer runs: its only caller is the `Orchestrator`
(`decisions/0001`), and the whole `lucid_recall` package is not even in the
Brain's import closure. `scripts/lens_reachability.py` reports it under
"UNREACHABLE from the Brain — a hard no: no code path can even load these".

WHY IT IS TWO ADAPTERS AND NOT A REWRITE
----------------------------------------
The router wants two collaborators it describes precisely and the Brain has
both under different names:

  * `social_lens.identify(frame)` returning an object with `.match` — the Brain
    has `face_live.FaceRecall.identify(frame)` returning a DICT, and its
    negative answers already distinguish the cases the router cares about
    (unavailable / veiled / no face / not enrolled). `_SocialShim` maps the
    dict onto the attribute shape, preserving that distinction, because
    "not in your contacts" is a claim about the world and may only be made when
    we actually looked.
  * `memory_index.get(text) -> str` — the Brain has `Retriever.search(query)`.
    `_MemoryShim` is that call plus a summary field read.

Neither shim invents an answer. A miss stays a miss, and the router's own
fallback ("No result") is what the wearer gets rather than a guess.

THE VEIL
--------
The router already gates itself on `allow_recall()`, which is the RIGHT gate
for this lens and not the same one capture uses: incognito stops keeping new
memories, it does not stop you asking what you already know. A full pause is
"deaf and blind" and silences it. Passing the Brain's own gate here means the
lens honours the wearer's posture without a second implementation of it.
"""
from __future__ import annotations

from .veil import RECALL_SURVIVES_INCOGNITO, VeilGate

import logging
from typing import Any, Optional

log = logging.getLogger("dreamlayer.lucid_live")

#: How many memory rows a fact question folds into one answer. Small: the
#: result is one spoken line on a glass, not a search page.
TOP_K = 3


class _Match:
    # `confidence` is in the slots because the router reads `m.confidence` off
    # the match. Omitting it made the assignment raise AttributeError and the
    # whole face branch fail as "unavailable" — a lens reporting no camera on a
    # device whose camera had just recognised somebody.
    __slots__ = ("contact", "confidence")

    def __init__(self, contact, confidence: float = 0.0):
        self.contact = contact
        self.confidence = float(confidence)


class _Contact:
    """The two fields the router reads off a match, and nothing more."""

    def __init__(self, name: str, contact_id: str, detail: str = ""):
        self.name = name
        self.contact_id = contact_id
        self._detail = detail

    def context_line(self) -> str:
        return self._detail


class _Result:
    """`SocialLens.identify`'s shape, from `FaceRecall.identify`'s dict.

    The negative flags are carried across rather than collapsed to one "no",
    because the router says different things for each and they are not the same
    statement: "not in your contacts" asserts that we looked and did not find
    them, while "the veil is up" asserts that we never looked at all.
    """

    def __init__(self, got: dict):
        got = got if isinstance(got, dict) else {}
        self.match = None
        if got.get("known"):
            self.match = _Match(_Contact(str(got.get("name") or ""),
                                         str(got.get("contact_id") or ""),
                                         str(got.get("detail") or "")),
                                float(got.get("confidence") or 0.0))
        reason = str(got.get("reason") or "")
        self.veiled = reason == "veiled" or bool(got.get("veiled"))
        self.unavailable = reason in ("unavailable", "no_model") or \
            bool(got.get("unavailable"))
        self.no_face = reason in ("no_face", "no face") or bool(got.get("no_face"))


class _SocialShim:
    def __init__(self, brain):
        self.brain = brain

    def identify(self, frame):
        try:
            face = self.brain.face_recall()
            if face is None:
                return _Result({"known": False, "reason": "unavailable"})
            return _Result(face.identify(frame))
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lucid] face identify failed: %s", type(exc).__name__)
            return _Result({"known": False, "reason": "unavailable"})


class _MemoryShim:
    """The router's `get(text) -> str`, over what the Brain actually keeps.

    NOT the purge retriever. `Brain._retriever_for_purge()` builds
    `Retriever(db, None, ann)` — `embedder=None`, which falls back to
    `MockEmbeddingProvider`, a 32-d bag-of-word-hashes its own docstring calls
    "a *test fixture*, not an intelligence tier". Harmless where it is used
    (purging needs `evict`/`purge_all`, never a similarity) and exactly wrong
    for a recall answer.

    `Brain.memories()` is the assembled read the phone's Memories tab shows —
    places kept, people met, favours owed, dated reminders — and it is the
    wearer's real memory rather than a proxy for it. Ranking uses the same
    token-overlap `similarity` the dedup pass uses: explainable, dependency-free,
    and honest about being lexical rather than semantic.

    A miss returns "" and the router falls through to its own "No result". This
    shim never composes an answer out of near-misses.
    """

    #: Below this overlap a row is not an answer to the question, and offering
    #: it anyway is worse than saying nothing — the wearer would have to notice
    #: for themselves that it does not fit.
    #:
    #: This is LEXICAL, so it does not stem: "who did I meet at the expo" scores
    #: 0.167 against "met Sarah at the expo" and is correctly refused, because
    #: `meet` and `met` are different tokens. That is a real limitation and the
    #: right response is to leave the bar where it is — dropping it to catch
    #: this one pair admits far more genuine mismatches than it rescues, and a
    #: confidently wrong memory is the most expensive answer this lens can give.
    #: `test_lucid_recall.py` pins the miss so it stays a known shape rather
    #: than a surprise.
    MIN_OVERLAP = 0.2

    def __init__(self, brain):
        self.brain = brain

    def get(self, text: str) -> str:
        if not (text or "").strip():
            return ""
        try:
            rows = (self.brain.memories(limit=60) or {}).get("memories") or []
        except Exception as exc:                     # noqa: BLE001
            log.debug("[lucid] memories unavailable: %s", type(exc).__name__)
            return ""
        from ...memory.dedup import similarity
        best, best_score = "", 0.0
        for row in rows:
            line = str(row.get("summary") or "").strip()
            if not line:
                continue
            score = similarity(text, line)
            if score > best_score:
                best, best_score = line, score
        return best if best_score >= self.MIN_OVERLAP else ""


class LucidLive:
    """The Brain's one router, built on first use and held for the session."""

    def __init__(self, brain):
        self.brain = brain
        self._router = None
        #: Answers this lens actually produced — not "a router exists".
        self.answered = 0

    def router(self):
        if self._router is None:
            from ...lucid_recall.router import LucidRecall
            self._router = LucidRecall(social_lens=_SocialShim(self.brain),
                                       memory_index=_MemoryShim(self.brain),
                                       privacy=VeilGate(self.brain, recall=RECALL_SURVIVES_INCOGNITO))
        return self._router

    def query(self, text: str = "", frame=None) -> dict:
        try:
            res = self.router().query(text=text or None, camera_frame=frame)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[lucid] query failed: %s", type(exc).__name__)
            return {"ok": False, "answer": "", "kind": "unknown",
                    "confidence": 0.0}
        kind = getattr(getattr(res, "query_type", None), "value", "unknown")
        answer = str(getattr(res, "answer", "") or "")
        source = getattr(res, "source", None)
        if source:                       # "No result" has no source and is not
            self.answered += 1           # an answer this lens gets credit for
        return {"ok": True, "answer": answer, "kind": str(kind),
                "confidence": round(float(getattr(res, "confidence", 0.0)), 3),
                "source": source,
                "contact_id": getattr(res, "contact_id", None),
                "detail": getattr(res, "detail", "") or ""}

    def status(self) -> dict:
        return {"answered": self.answered, "live": self.answered > 0}


def lucid(brain) -> LucidLive:
    got: Optional[Any] = getattr(brain, "_lucid", None)
    if got is None:
        got = LucidLive(brain)
        brain._lucid = got
    return got
