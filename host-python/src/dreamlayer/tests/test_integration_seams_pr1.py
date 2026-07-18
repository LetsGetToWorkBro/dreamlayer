"""PR1 integration-seam tests — verify every adapter's FALLBACK path (the deps
are optional and absent in CI). Each adapter must behave correctly with no
extra install, leaving core behaviour unchanged.
"""
from __future__ import annotations
import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import MockEmbeddingProvider
from dreamlayer.memory.retrieval import Retriever


def _seeded_db():
    db = MemoryDB(path=":memory:")
    db.add_memory("Promise", "Send Marcus the signed lease by Friday", confidence=0.9)
    db.add_memory("Object", "Snake plant on the sill water every 2 weeks", confidence=0.6)
    db.add_memory("Place", "Left the bike on 4th and Alder north rack", confidence=0.7)
    return db


# --- memory: local embedder falls back to the deterministic mock -------------
def test_local_embedder_fallback(monkeypatch):
    # Force the "sentence-transformers not installed" branch explicitly (the
    # module-global _HAS_ST flag in embedder_local.py) instead of relying on
    # the package actually being absent: with the optional dep installed
    # (issue #449), LocalEmbeddingProvider used to load the real 384-d MiniLM
    # model here and this assertion (pinned to the 32-d mock width) failed
    # for environment reasons, not a real regression. Mirrors
    # test_embedder_local_real.py::TestMockFallback
    # .test_forced_unavailable_degrades_to_mock_without_raising, which proves
    # the same _HAS_ST guard in an environment where the dep IS installed.
    from dreamlayer.memory import embedder_local
    from dreamlayer.memory.embedder_local import LocalEmbeddingProvider
    monkeypatch.setattr(embedder_local, "_HAS_ST", False)
    emb = LocalEmbeddingProvider()
    v = emb.embed("snake plant")
    assert isinstance(v, list) and len(v) == MockEmbeddingProvider.DIM
    assert abs(sum(x * x for x in v) - 1.0) < 1e-6  # normalized


# --- memory: vector/chroma/lance stores match the linear Retriever -----------
@pytest.mark.parametrize("store_path", [
    "dreamlayer.memory.vector_store:VectorStore",
    "dreamlayer.memory.chroma_store:ChromaStore",
    "dreamlayer.memory.lance_store:LanceStore",
])
def test_vector_stores_fallback_match_retriever(store_path):
    import importlib
    mod, cls = store_path.split(":")
    Store = getattr(importlib.import_module(mod), cls)
    db = _seeded_db()
    emb = MockEmbeddingProvider()
    got = Store(db, embedder=emb).search("marcus lease", top_k=2)
    ref = Retriever(db, embedder=emb).search("marcus lease", top_k=2)
    assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]


# --- lucid_recall: dense router picks the nearest exemplar linearly ----------
def test_dense_router_fallback():
    from dreamlayer.lucid_recall.usearch_router import DenseRouter
    r = DenseRouter()
    r.add("recall", "what did I say about the lease")
    r.add("people", "who is marcus and what does he do")
    assert r.route("remind me about the signed lease") == "recall"
    assert r.route("tell me about marcus") == "people"
    assert DenseRouter().route("anything") is None  # empty router


# --- lucid_recall: mem0 layer dedup + privacy guard --------------------------
def test_mem0_layer_fallback_and_privacy():
    from dreamlayer.lucid_recall.mem0_layer import Mem0Layer

    class _Veil:
        def __init__(self, on): self._on = on
        def allow_capture(self): return self._on

    m = Mem0Layer()
    assert m.add("marcus owes the lease") is True
    assert m.add("marcus owes the lease") is True         # dedup, not duplicated
    assert len([r for r in m._local if "lease" in r["text"]]) == 1
    hits = m.search("lease")
    assert hits and "lease" in hits[0]["text"]

    blocked = Mem0Layer(privacy=_Veil(False))
    assert blocked.add("secret") is False                 # veil down → refuses


# --- memory: typed doc schema round-trips (dataclass fallback) ---------------
def test_memory_doc_fallback():
    from dreamlayer.memory.doc_schema import MemoryDoc
    d = MemoryDoc(kind="Place", summary="bike on 4th", ts=42)
    row = d.to_row()
    assert row["kind"] == "Place" and row["summary"] == "bike on 4th" and row["ts"] == 42


# --- voice: VAD energy fallback; ASR empty fallback --------------------------
def test_vad_and_asr_fallback(monkeypatch):
    # Force the "silero-vad not installed" branch explicitly (the module-global
    # _HAS_SILERO flag in vad_gate.py) instead of relying on the package
    # actually being absent: with silero-vad installed (issue #460), is_speech()
    # preferred the real loaded model here and it correctly classified this
    # alternating-tone burst as NOT speech, failing the energy-fallback
    # assertion below for environment reasons, not a real regression. Mirrors
    # test_voice_pipeline_real.py::TestVADFallback
    # .test_forced_unavailable_uses_energy_heuristic, which proves the same
    # _HAS_SILERO guard in an environment where the dep IS installed.
    from dreamlayer.orchestrator import vad_gate
    from dreamlayer.orchestrator.vad_gate import SileroVADGate
    monkeypatch.setattr(vad_gate, "_HAS_SILERO", False)
    gate = SileroVADGate(threshold=0.05)
    assert gate.is_speech([0.5, -0.6, 0.55, -0.5] * 40) is True   # loud
    assert gate.is_speech([0.0, 0.001, -0.001] * 40) is False     # silence
    assert gate.is_speech([]) is False

    # Force the "faster-whisper not installed" branch explicitly (the
    # module-global _HAS_FW flag in asr_faster_whisper.py): the "" result
    # below only holds via the `_model is None` early return, and with
    # faster-whisper installed (issue #460) transcribe() would exercise the
    # real model against a nonexistent file instead, an unrelated code path.
    # Mirrors test_voice_pipeline_real.py::TestASRFallback
    # .test_forced_unavailable_returns_empty_without_raising, which proves the
    # same _HAS_FW guard in an environment where the dep IS installed.
    from dreamlayer.orchestrator import asr_faster_whisper
    from dreamlayer.orchestrator.asr_faster_whisper import FasterWhisperASR
    monkeypatch.setattr(asr_faster_whisper, "_HAS_FW", False)
    assert FasterWhisperASR().transcribe("nonexistent.wav") == ""  # no dep → ""


# --- structured: LLM intent parser falls back to the regex parser ------------
def test_llm_intent_parser_fallback():
    from dreamlayer.reality_compiler.intent_parser import IntentParser
    from dreamlayer.reality_compiler.intent_parser_llm import LLMIntentParser
    text = "round timer 3 minutes"
    ref = IntentParser().parse(text)
    got = LLMIntentParser().parse(text)          # no llm wired → regex path
    assert got.type == ref.type


def test_llm_suggestion_cannot_escape_the_closed_grammar():
    """The LLM parser is a suggestion layer, never an authority: an adversarial
    'model' cannot fabricate a behavior outside the deterministic grammar — the
    result is always a schema-legal BehaviorIntent decided by the regex matcher."""
    from dreamlayer.reality_compiler.intent_parser_llm import LLMIntentParser
    from dreamlayer.reality_compiler.schema import BehaviorIntent
    evil = lambda _t: '{"behavior": "WIPE_ALL_MEMORIES", "pulse_hz": 9999}'
    p = LLMIntentParser(llm=evil)
    p.available = True                            # force the structured path on
    intent = p.parse("round timer 3 minutes")
    assert isinstance(intent, BehaviorIntent)     # still schema-legal
    assert intent.type and "WIPE" not in str(intent.type).upper()


# --- structured: answer validation is a safe passthrough ---------------------
def test_answer_validate_passthrough():
    from dreamlayer.orchestrator.answer_validate import validate_answer
    card = {"type": "AnswerCard", "primary": "You owe Marcus the lease", "confidence": 0.8, "extra": 1}
    out = validate_answer(card)
    assert out["primary"] == card["primary"] and out.get("extra") == 1


# --- llm: litellm backend delegates to the built-in dispatch when absent -----
def test_litellm_backend_delegates(monkeypatch):
    from dreamlayer.ai_brain import litellm_backend as lb
    calls = {}

    def _fake_builtin(config, prompt, http_post=None, timeout=30.0):
        calls["prompt"] = prompt
        return "built-in answer"

    monkeypatch.setattr(lb, "_builtin_cloud_chat", _fake_builtin)
    # _HAS_LITELLM is False in CI, so litellm_chat must delegate.
    out = lb.litellm_chat(config=object(), prompt="hi")
    assert out == "built-in answer" and calls["prompt"] == "hi"
    assert lb._model_for(type("C", (), {"cloud_provider": "anthropic", "cloud_model": "claude-3-5-haiku"})()) == "anthropic/claude-3-5-haiku"
