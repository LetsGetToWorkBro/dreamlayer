"""Tests for PlaceReactor — the ambient trust signal (Halo Cinema v1)."""
from dreamlayer.dream_mode.place_reactor import PlaceReactor, RAMP_S, AMBIENT_HZ
from dreamlayer.orchestrator.recall_context import RecallContext
from dreamlayer.hud import themes as T


def make_ctx(signature=None, anchors=None):
    ctx = RecallContext()
    ctx.place_signature = signature
    ctx.world_anchors = anchors
    return ctx


def test_no_output_without_place():
    r = PlaceReactor()
    assert r.tick(make_ctx()) is None


def test_novel_place_biases_toward_attention():
    r = PlaceReactor()
    cmd = r.tick(make_ctx("alley_007"))
    assert cmd["bias"] == "novel"
    assert cmd["t"] == "palette"


def test_known_place_biases_toward_memory():
    r = PlaceReactor()
    anchors = [{"id": "a1", "summary": "Keys here", "confidence": 0.9}]
    cmd = r.tick(make_ctx("kitchen_001", anchors))
    assert cmd["bias"] == "trust"


def test_bias_targets_drift_b_slot():
    r = PlaceReactor()
    cmd = r.tick(make_ctx("kitchen_001"))
    assert cmd["colors"][0]["idx"] == T.DYNAMIC_SLOTS["drift_b"]


def test_ramp_reaches_full_over_8_seconds():
    r = PlaceReactor()
    ticks = int(RAMP_S * AMBIENT_HZ)
    for _ in range(ticks):
        r.tick(make_ctx("alley_007"))
    assert r.ramp == 1.0


def test_ramp_is_gradual_not_a_flash():
    r = PlaceReactor()
    first = r.tick(make_ctx("alley_007"))
    ticks = int(RAMP_S * AMBIENT_HZ)
    for _ in range(ticks):
        last = r.tick(make_ctx("alley_007"))
    # chroma moved monotonically toward the target, starting near neutral
    assert abs(first["colors"][0]["cr"] - 450) < abs(last["colors"][0]["cr"] - 450)


def test_ramp_resets_on_place_change():
    r = PlaceReactor()
    for _ in range(8):
        r.tick(make_ctx("alley_007"))
    mid_ramp = r.ramp
    r.tick(make_ctx("plaza_002"))
    assert r.ramp < mid_ramp


def test_place_becomes_known_once_anchored():
    """A place seen with anchors stays trusted on later visits even when the
    anchors are not re-supplied."""
    r = PlaceReactor()
    anchors = [{"id": "a1", "summary": "x", "confidence": 0.5}]
    r.tick(make_ctx("kitchen_001", anchors))
    r.tick(make_ctx("alley_007"))          # leave
    cmd = r.tick(make_ctx("kitchen_001"))  # return, no anchors passed
    assert cmd["bias"] == "trust"


def test_ycbcr_values_in_display_range():
    r = PlaceReactor()
    for _ in range(20):
        cmd = r.tick(make_ctx("alley_007"))
    c = cmd["colors"][0]
    assert 0 <= c["y"] <= 1023
    assert 0 <= c["cb"] <= 1023
    assert 0 <= c["cr"] <= 1023
