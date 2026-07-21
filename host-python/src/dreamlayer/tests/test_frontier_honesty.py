"""docs/FRONTIER.md — the staged-integration map stays honest.

Two invariants: the doc exists and states the no-egress-CSP rationale, and none
of the staged (not-built) browser/firmware items has quietly become a claimed
capability without code — the doc and the registry must not contradict.
"""
from __future__ import annotations

from pathlib import Path

_DOC = Path(__file__).resolve().parents[4] / "docs" / "FRONTIER.md"

# staged items: NOT allowed to appear as capability keys until really built
_STAGED_KEYS = ("bergamot", "webllm", "smolvlm", "pmtiles", "protomaps",
                "wamr", "omiglass", "brush_splat", "kokoro_web")


def test_frontier_doc_exists_and_states_the_rule():
    text = _DOC.read_text()
    assert "no-egress CSP" in text
    assert "capabilities.py" in text          # the honesty rule is written down
    for name in ("kokoro-js", "bergamot", "WebLLM", "SmolVLM", "PMTiles",
                 "WAMR", "omiGlass", "Brush", "microWakeWord"):
        assert name in text, f"frontier doc lost its {name} entry"


def test_staged_items_are_not_claimed_as_capabilities():
    from dreamlayer import capabilities as C
    keys = {c.key for c in C.CAPABILITIES}
    for staged in _STAGED_KEYS:
        assert staged not in keys, f"{staged} is staged in FRONTIER.md but claimed in capabilities"


def test_shipped_equivalences_really_exist():
    # the doc's "already shipped" table must point at real caps
    from dreamlayer import capabilities as C
    keys = {c.key for c in C.CAPABILITIES}
    for key in ("kokoro_tts", "vector_search", "doc_read", "wake_word",
                "sound_events", "bird_song", "mesh_range"):
        assert key in keys, f"FRONTIER.md references missing cap {key}"
