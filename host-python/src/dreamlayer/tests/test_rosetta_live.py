"""test_rosetta_live.py — Rosetta Live (INNOVATION_SESSION 4.6): the "ear" half,
offline. Someone speaks Spanish; the English streams onto the glass. As of the
figment-migration pilot this rides a budget-proven figment (named slots), not a
per-utterance SpokenCaptionCard. Veil-gated; the offline Argos backend is wired
by default."""
from __future__ import annotations

from dreamlayer.main import build
from dreamlayer.rosetta import RosettaLens


def _text_slots(orch, fid):
    """The last value pushed into each named slot of figment `fid`."""
    slots = {}
    for f in orch.bridge.raw_frames:
        if f.get("t") == "figment_text" and f.get("id") == fid:
            slots[f.get("slot", "")] = f.get("text")
    return slots


def test_translate_heard_streams_the_translation_into_a_figment():
    orch = build(":memory:")
    orch.rosetta = RosettaLens(translate_fn=lambda t, tgt: "hello, thanks",
                               engine="test")
    out = orch.translate_heard("hola, gracias", speaker="Maya")
    assert out["surface"] == "figment"
    # the Rosetta figment was put + swapped onto the stage
    frames = orch.bridge.raw_frames
    assert any(f.get("t") == "figment_put" for f in frames)
    assert orch._active_figment == out["figment_id"]
    # and the utterance filled the named slots
    slots = _text_slots(orch, out["figment_id"])
    assert "hello" in slots["translation"].lower()
    assert "hola" in slots["original"].lower()
    assert slots["langs"] == "ES → EN"


def test_second_utterance_reuses_the_same_figment():
    orch = build(":memory:")
    orch.rosetta = RosettaLens(translate_fn=lambda t, tgt: "hi", engine="test")
    a = orch.translate_heard("hola")
    puts_before = sum(1 for f in orch.bridge.raw_frames if f.get("t") == "figment_put")
    b = orch.translate_heard("gracias")
    puts_after = sum(1 for f in orch.bridge.raw_frames if f.get("t") == "figment_put")
    assert a["figment_id"] == b["figment_id"]   # one lens, streamed into
    assert puts_after == puts_before            # not re-deployed per utterance


def test_same_language_passes_through():
    orch = build(":memory:")
    out = orch.translate_heard("hello there")     # en detected == target
    slots = _text_slots(orch, out["figment_id"])
    assert "hello there" in slots["translation"].lower()


def test_translate_heard_is_veil_gated():
    orch = build(":memory:")
    orch.privacy.pause()
    assert orch.translate_heard("hola, gracias") is None


def test_argos_backend_is_wired_by_default():
    orch = build(":memory:")
    # the offline backend seam is attached (identity when argos isn't installed)
    assert orch.rosetta._engine == "argos"
