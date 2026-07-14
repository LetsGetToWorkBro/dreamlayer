"""Re-audit wave 5C: the default (no-ML-deps) perception paths must not lie on
live input — the configuration the fallback rungs explicitly claim to serve.

  * Int-1: the Veritas verdict parser inverted negations ("not correct" →
    supported), flashing a green card on a refuted claim.
  * Int-3: the energy-VAD fallback normalised by the window's own peak, so
    near-silence read as speech and segments never endpointed on silence.
  * Int-4: the offline vision rung floored confidence at ≥0.5, so a wall/noise
    match sailed through the recognizer's confidence gate.
  * Int-5: text_density normalised by dynamic range, so sensor noise on a flat
    wall saturated to "maximal text".
  * Int-6: LucidRecall matched face keywords as substrings and dead-ended
    camera-less face queries — fact questions returned "No result".
  * Int-8: tier-1 ingest minted "Person: Tomorrow/Thursday/Remember" from
    grammatical sentence-initial capitals.
"""
from __future__ import annotations

import numpy as np


# --- Int-1: verdict negation -------------------------------------------------

def test_verdict_negation_flips_polarity():
    from dreamlayer.ai_brain.verify import parse_verdict
    assert parse_verdict("VERDICT: Not correct — Canberra is the capital")["verdict"] == "disputed"
    assert parse_verdict("That is not accurate.")["verdict"] == "disputed"
    assert parse_verdict("isn't true")["verdict"] == "disputed"
    assert parse_verdict("never accurate")["verdict"] == "disputed"
    # un-negated verdicts are unchanged
    assert parse_verdict("VERDICT: SUPPORTED — checks out")["verdict"] == "supported"
    assert parse_verdict("that is correct")["verdict"] == "supported"
    assert parse_verdict("unverified — no data")["verdict"] == "unverified"


# --- Int-3: energy VAD -------------------------------------------------------

def test_energy_vad_calls_near_silence_silence():
    from dreamlayer.orchestrator.vad_gate import SileroVADGate
    g = SileroVADGate()
    g._model = None                               # force the energy fallback
    assert g.is_speech([3, -3, 3, -3] * 800) is False     # ±3 LSB int16 = silence
    assert g.is_speech([5, 0, -5, 0] * 800) is False      # peak-5 quiet tone
    assert g.is_speech([12000, -9000, 15000, -11000] * 800) is True  # real speech
    assert g.is_speech([0.4, -0.3, 0.5] * 800) is True    # float speech
    assert g.is_speech([0.001, -0.001] * 800) is False    # float silence


# --- Int-4: offline vision confidence gate -----------------------------------

def test_heuristic_vision_rejects_wall_and_noise():
    from dreamlayer.object_lens.classify_backends import HeuristicVisionClassifier
    from dreamlayer.object_lens.recognizer import ObjectRecognizer
    clf = HeuristicVisionClassifier()
    noise = np.random.RandomState(0).randint(0, 256, (48, 48, 3), dtype=np.uint8)
    wall = (np.full((48, 48, 3), 128, dtype=np.int16)
            + np.random.RandomState(1).randint(-2, 3, (48, 48, 3))).astype(np.uint8)
    for frame in (noise, wall):
        out = clf(frame)
        # either no match, or a confidence below the recognizer's 0.5 gate
        assert out is None or out[1] < 0.5, out
    rec = ObjectRecognizer(classify_fn=clf, min_confidence=0.5)
    assert rec.recognize(noise) is None           # gated out, not labelled


# --- Int-5: text density -----------------------------------------------------

def test_text_density_flat_wall_scores_near_zero():
    from dreamlayer.ai_brain.perception import text_density
    wall = np.full((64, 64), 128.0) + np.random.RandomState(0).randint(-1, 2, (64, 64))
    assert text_density(wall) < 0.1               # near-flat, not saturated
    stripes = np.zeros((64, 64)); stripes[:, ::2] = 255
    assert text_density(stripes) > 0.5            # genuine dense edges score high


# --- Int-6: LucidRecall routing ----------------------------------------------

def test_lucid_recall_routes_fact_queries_to_memory():
    from dreamlayer.lucid_recall.router import LucidRecall

    class Mem:
        def get(self, q):
            return "the Bistro on 5th" if q else None

    r = LucidRecall(memory_index=Mem())
    for q in ["what was the name of the restaurant Sarah mentioned",
              "when is the tournament",
              "remind me what we discussed about the lease"]:
        res = r.query(q)                          # no camera frame
        assert res.answer == "the Bistro on 5th", (q, res.answer)


# --- Int-8: person fabrication ----------------------------------------------

def test_tier1_does_not_fabricate_persons_from_sentence_leads():
    from dreamlayer.pipelines.ingest import _extract_tier1

    def persons(t):
        return {e.meta["person"] for e in _extract_tier1(t, {}) if e.kind == "person"}

    assert persons("Remember to call the plumber") == set()
    assert "Tomorrow" not in persons("Tomorrow I fly to Paris")
    assert persons("Thursday works for me") == set()
    assert "Please" not in persons("Please send the deck")
    # a real, multi-word name still registers
    assert "Marcus Chen" in persons("I met Marcus Chen at the expo")
