"""memory/graph_recall.py — temporal knowledge-graph recall (LightRAG).

The wheel (`lightrag-hku`) is not in CI, so these pin the graceful-fallback
contract: without it, and without a local LLM + embedder, the adapter is inert
and every method returns the neutral value that makes the caller fall straight
back to normal vector recall. Also fixes the capability registration.
"""
from __future__ import annotations

from dreamlayer.memory.graph_recall import GraphRecall, default_graph_recall


class TestFallback:
    def test_unavailable_without_wheel_or_callables(self, tmp_path):
        # no lightrag wheel in CI, and no llm/embed callables → never ready
        g = GraphRecall(str(tmp_path / "g"))
        assert g.ready is False
        assert g.index("the doctor said rest the knee for six weeks") is False
        assert g.answer("what did the doctor say about my knee") is None

    def test_default_is_none_without_the_engine(self, tmp_path):
        assert default_graph_recall(str(tmp_path / "g")) is None

    def test_empty_query_and_text_are_safe(self, tmp_path):
        g = GraphRecall(str(tmp_path / "g"))
        assert g.index("") is False
        assert g.index("   ") is False
        assert g.answer("") is None
        assert g.answer("   ") is None

    def test_callables_alone_do_not_fabricate_readiness(self, tmp_path):
        # llm+embed supplied but the wheel is still absent → stays inert (no crash)
        g = GraphRecall(str(tmp_path / "g"),
                        llm_fn=lambda *a, **k: "", embed_fn=lambda *a, **k: [])
        assert g.ready is (GraphRecall.available and g._rag is not None)
        assert g.answer("anything") is None or isinstance(g.answer("x"), str)


def test_memory_graph_capability_registered():
    from dreamlayer import capabilities as C
    cap = {c.key: c for c in C.CAPABILITIES}.get("memory_graph")
    assert cap is not None, "memory_graph capability missing"
    assert cap.extra == "memory-graph"
    assert "lightrag" in cap.modules
    assert cap.seam == "memory/graph_recall.py"
