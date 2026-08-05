"""LucidRecall, Brain-side — the lens that could not even be loaded.

`scripts/lens_reachability.py` reported `dreamlayer.lucid_recall` under
"UNREACHABLE from the Brain (3) — a hard no: no code path can even load these".
Not dormant, not unwired: absent from the Brain's import closure entirely. Its
only constructor was the `Orchestrator` (decisions/0001).

The router itself was complete. What it wanted was two collaborators the Brain
already had under different names and shapes, so this is two adapters and a
gate, not a rewrite.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server.lucid_live import (
    LucidLive, _MemoryShim, _Result, _SocialShim,
)
from dreamlayer.ai_brain.server.veil import VeilGate


def _lucid_gate(brain):
    """The gate this lens takes — now the only gate there is.

    Lucid Recall used to be the ONE Brain-side site that kept recall open while
    veiled, and this helper existed to pin that it asked for that posture. The
    argument it was making won: recall is unrestricted everywhere
    (decisions/0009), so there is no posture left to declare and the helper is
    just the shared gate.
    """
    return VeilGate(brain)


class _Brain:
    def __init__(self, veiled=False, face=None, memories=None):
        self._veiled = veiled
        self._face = face
        self._memories = memories or []

    def incognito_now(self):
        return self._veiled

    def face_recall(self):
        return self._face

    def memories(self, limit=40):
        return {"memories": self._memories}


class _Face:
    def __init__(self, out):
        self.out = out

    def identify(self, frame):
        return self.out


def _mem(*summaries):
    return [{"id": f"m{i}", "kind": "Note", "summary": s, "ts": 0}
            for i, s in enumerate(summaries)]


class TestTheGateIsTheRightOne:
    def test_recall_survives_incognito(self):
        """The load-bearing privacy decision, and it is a mapping not a hole.

        `PrivacyGate.allow_recall` is blocked by an explicit PAUSE only —
        incognito "stops keeping new memories, not recalling old ones". The
        Brain has no pause input at all: its whole posture is `incognito_now()`,
        every term of which is about capture. Silencing recall under incognito
        would take away the wearer's own memory in exactly the session where
        they most likely want a quiet private lookup.
        """
        assert _lucid_gate(_Brain(veiled=True)).allow_recall() is True

    def test_the_argument_this_lens_made_is_now_the_whole_rule(self):
        """This lens was the dissenter, and it was right.

        Eleven other Brain-side gates tied recall to capture; this one did not,
        citing `PrivacyGate`'s own semantics. That reading is now the only one
        (decisions/0009), so what used to be a per-lens declaration is a
        property of the gate itself — and the thing worth pinning is that no
        caller can reintroduce a posture argument to opt back out.
        """
        import inspect

        from dreamlayer.ai_brain.server.veil import VeilGate
        params = inspect.signature(VeilGate.__init__).parameters
        assert list(params) == ["self", "brain"], (
            "VeilGate grew a knob again — recall is unrestricted for every "
            f"lens, not a per-site choice: {list(params)}")

    def test_capture_still_fails_closed(self):
        assert _lucid_gate(_Brain(veiled=True)).allow_capture() is False
        assert _lucid_gate(_Brain(veiled=False)).allow_capture() is True

    def test_an_unreadable_posture_refuses_capture(self):
        class _Boom:
            def incognito_now(self):
                raise RuntimeError("unreadable")
        assert _lucid_gate(_Boom()).allow_capture() is False

    def test_no_phantom_flag_is_read(self):
        """An earlier draft read `config.pause_capture`, which does not exist on
        `BrainConfig` — `getattr(..., False)` made it return True anyway, with a
        check that looked like it did something. Reading a setting nobody writes
        is worse than not reading one: the next person believes the control is
        there. If a real pause is added Brain-side, `allow_recall` is what must
        learn about it."""
        import inspect

        from dreamlayer.ai_brain.server import veil
        src = inspect.getsource(veil.VeilGate.allow_recall)
        assert "pause_capture" not in src.split('"""')[-1], (
            "allow_recall is reading a config flag again — check it exists")
        from dreamlayer.ai_brain.server.store import BrainConfig
        assert not hasattr(BrainConfig(), "pause_capture")


class TestTheFaceAdapter:
    def test_a_known_contact_becomes_a_match(self):
        got = _Result({"known": True, "name": "Maya", "contact_id": "c1",
                       "confidence": 0.91, "detail": "met at the expo"})
        assert got.match is not None
        assert got.match.contact.name == "Maya"
        assert got.match.contact.context_line() == "met at the expo"

    def test_the_negatives_stay_distinguishable(self):
        # "Not in your contacts" asserts we LOOKED and did not find them;
        # "the veil is up" asserts we never looked. Collapsing them into one
        # "no" would make the lens claim knowledge it does not have.
        assert _Result({"known": False, "reason": "veiled"}).veiled is True
        assert _Result({"known": False, "reason": "unavailable"}).unavailable
        assert _Result({"known": False, "reason": "no_face"}).no_face is True
        plain = _Result({"known": False})
        assert not (plain.veiled or plain.unavailable or plain.no_face)

    def test_a_missing_face_host_is_unavailable_not_a_denial(self):
        got = _SocialShim(_Brain(face=None)).identify(object())
        assert got.match is None and got.unavailable is True

    def test_a_face_host_that_raises_is_unavailable(self):
        class _Boom:
            def identify(self, frame):
                raise RuntimeError("camera gone")
        got = _SocialShim(_Brain(face=_Boom())).identify(object())
        assert got.unavailable is True

    def test_garbage_from_the_face_host_names_nobody(self):
        assert _Result("not a dict").match is None
        assert _Result(None).match is None


class TestTheMemoryAdapter:
    def test_it_finds_the_relevant_memory(self):
        b = _Brain(memories=_mem("Marcus owes me the lease by Friday",
                                 "bought oat milk"))
        assert "lease" in _MemoryShim(b).get("what did Marcus say about the lease")

    def test_an_irrelevant_store_answers_nothing(self):
        # A near-miss offered as an answer is worse than silence: the wearer has
        # to notice for themselves that it does not fit.
        b = _Brain(memories=_mem("bought oat milk", "returned the drill"))
        assert _MemoryShim(b).get("what did Marcus say about the lease") == ""

    def test_an_empty_question_asks_nothing(self):
        b = _Brain(memories=_mem("Marcus owes me the lease"))
        assert _MemoryShim(b).get("") == ""
        assert _MemoryShim(b).get("   ") == ""

    def test_a_broken_memories_read_is_not_fatal(self):
        class _Boom(_Brain):
            def memories(self, limit=40):
                raise RuntimeError("db gone")
        assert _MemoryShim(_Boom()).get("anything") == ""

    def test_it_does_not_use_the_purge_retriever(self):
        """`_retriever_for_purge` builds `Retriever(db, None, ann)` — a mock
        embedder its own docstring calls "a *test fixture*, not an intelligence
        tier". Harmless for purging, which needs `evict`/`purge_all` and never a
        similarity; exactly wrong for a recall answer."""
        import inspect

        from dreamlayer.ai_brain.server import lucid_live
        src = inspect.getsource(lucid_live._MemoryShim)
        assert "_retriever_for_purge" not in src.split('"""')[2]


class TestTheRouterAnswers:
    def _live(self, **kw):
        return LucidLive(_Brain(**kw))

    def test_a_fact_question_is_answered_from_memory(self):
        got = self._live(memories=_mem("Marcus owes me the lease by Friday")
                         ).query("what did Marcus say about the lease")
        assert got["ok"] is True
        assert "lease" in got["answer"]
        assert got["source"] == "memory"

    def test_a_face_question_with_a_frame_names_an_enrolled_contact(self):
        face = _Face({"known": True, "name": "Maya", "contact_id": "c1",
                      "confidence": 0.9})
        got = self._live(face=face).query("who is this", frame=object())
        assert got["answer"] == "Maya" and got["source"] == "social_lens"

    def test_a_face_question_with_no_frame_falls_through_to_memory(self):
        # A face question with nothing to look at is still worth a memory
        # lookup — the router says so explicitly.
        got = self._live(memories=_mem("Sarah at the expo, works in ceramics")
                         ).query("who is Sarah from the expo")
        assert "Sarah" in got["answer"] and got["source"] == "memory"

    def test_the_lexical_bar_refuses_an_inflected_near_miss(self):
        """A known limitation, pinned rather than papered over.

        `who did I MEET at the expo` scores 0.167 against `MET Sarah at the
        expo` — different tokens, no stemming — and is refused. Dropping
        MIN_OVERLAP to catch this one pair admits far more genuine mismatches
        than it rescues, and a confidently wrong memory is the most expensive
        answer this lens can give. If stemming is ever added, this test should
        FAIL and be retired.
        """
        from dreamlayer.memory.dedup import similarity
        assert similarity("who did I meet at the expo",
                          "met Sarah at the expo") < _MemoryShim.MIN_OVERLAP
        got = self._live(memories=_mem("met Sarah at the expo")
                         ).query("who did I meet at the expo")
        assert got["answer"] == "No result"

    def test_nothing_known_is_no_result_not_an_invention(self):
        got = self._live().query("what did Marcus say about the lease")
        assert got["answer"] == "No result" and got["source"] is None

    def test_only_a_sourced_answer_counts_as_live(self):
        live = self._live()
        live.query("what did Marcus say about the lease")
        assert live.answered == 0 and live.status()["live"] is False
        live2 = self._live(memories=_mem("Marcus owes me the lease"))
        live2.query("what about the lease")
        assert live2.answered == 1 and live2.status()["live"] is True

    def test_a_router_that_raises_is_not_fatal(self):
        live = self._live()
        live._router = type("_R", (), {
            "query": staticmethod(lambda **kw: (_ for _ in ()).throw(
                RuntimeError("boom")))})()
        assert live.query("anything")["ok"] is False


class TestTheBrainDrivesIt:
    def test_the_route_exists(self):
        import inspect

        from dreamlayer.ai_brain.server import server as s
        assert '"/dreamlayer/lucid": _post_lucid' in inspect.getsource(s)

    def test_lucid_query_through_the_brain(self):
        from dreamlayer.ai_brain.server.server import Brain
        b = Brain.__new__(Brain)
        got = Brain.lucid_query(b, "what did Marcus say")
        assert isinstance(got, dict) and "answer" in got

    def test_the_package_is_now_in_the_brains_closure(self):
        """The measurement that made this a "hard no": `lucid_recall` was not in
        the Brain's import closure at all. It is imported by `lucid_live`, which
        `server.py` reaches, so a checker run must find it now."""
        import importlib.util
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[4]
        spec = importlib.util.spec_from_file_location(
            "_lens", root / "scripts" / "lens_reachability.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        files = m._sources()
        _roots, reached = m._closure(
            m._import_graph(files), {m._module_name(p) for p in files})
        assert "dreamlayer.lucid_recall.router" in reached, (
            "LucidRecall left the Brain's closure again")
