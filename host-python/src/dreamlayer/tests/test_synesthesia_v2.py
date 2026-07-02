"""Tests for SynesthesiaCard v2: scene→phrase + 3-shape gestural sprite."""
import asyncio

import pytest

from dreamlayer.dream_mode.scene_describer import (
    GesturalSprite, SceneDescriber, sprite_from_phrase, _SHAPE_KINDS,
)
from dreamlayer.orchestrator.recall_context import RecallContext
from dreamlayer.hud import cards as C


def make_ctx(jpeg=b"\xff\xd8\xff fake"):
    ctx = RecallContext()
    ctx.camera_frame = jpeg
    return ctx


# ---------------------------------------------------------------------------
# Deterministic fallback gesture
# ---------------------------------------------------------------------------

def test_sprite_from_phrase_is_deterministic():
    a = sprite_from_phrase("warm cafe hum, cups and patience")
    b = sprite_from_phrase("warm cafe hum, cups and patience")
    assert a == b


def test_sprite_from_phrase_has_three_valid_shapes():
    sprite = sprite_from_phrase("familiar geometry, patient silence")
    assert len(sprite.shapes) == 3
    for s in sprite.shapes:
        assert s["kind"] in _SHAPE_KINDS
        assert 0 <= s["x"] <= 127
        assert 0 <= s["y"] <= 127
        assert 8 <= s["size"] <= 56


def test_different_phrases_give_different_gestures():
    a = sprite_from_phrase("soft light, still breathing, here")
    b = sprite_from_phrase("motion arrested, memory accumulating")
    assert a != b


# ---------------------------------------------------------------------------
# SceneDescriber tick — v2 card + sprite spec
# ---------------------------------------------------------------------------

def test_tick_returns_v2_card_offline():
    sd = SceneDescriber()          # no vision fn: deterministic fallback
    card = asyncio.run(sd.tick(make_ctx()))
    assert card["type"] == "SynesthesiaCard"
    assert card["version"] == 2
    assert len(card["shapes"]) == 3
    assert sd.last_sprite is not None


def test_tick_none_without_camera():
    sd = SceneDescriber()
    assert asyncio.run(sd.tick(RecallContext())) is None


def test_tick_uses_vlm_sprite_spec_when_valid():
    async def vision(jpeg, prompt):
        if "JSON" in prompt:
            return ('{"dominant": "#E06B52", "shapes": ['
                    '{"kind": "circle", "x": 44, "y": 56, "size": 36},'
                    '{"kind": "line", "x": 64, "y": 92, "size": 48},'
                    '{"kind": "triangle", "x": 96, "y": 48, "size": 16}]}')
        return "warm cafe hum cups and patience"
    sd = SceneDescriber(vision_fn=vision)
    card = asyncio.run(sd.tick(make_ctx()))
    assert card["dominant_color"] == 0xE06B52
    assert card["shapes"][0]["kind"] == "circle"


def test_tick_falls_back_on_bad_vlm_json():
    async def vision(jpeg, prompt):
        if "JSON" in prompt:
            return "not json at all"
        return "edges dissolving into ambient warmth"
    sd = SceneDescriber(vision_fn=vision)
    card = asyncio.run(sd.tick(make_ctx()))
    assert len(card["shapes"]) == 3   # deterministic fallback kicked in


# ---------------------------------------------------------------------------
# Card constructor
# ---------------------------------------------------------------------------

def test_v2_card_layout_anchors_sprite_bottom_half():
    card = C.synesthesia_card_v2("phrase", 0x2CC79A, [])
    sprite_zone = card["layout"]["sprite"]
    assert (sprite_zone["x"], sprite_zone["y"]) == (64, 128)
    assert (sprite_zone["w"], sprite_zone["h"]) == (128, 128)


def test_v2_card_caps_long_descriptions():
    card = C.synesthesia_card_v2("x" * 200, 0x2CC79A, [])
    assert len(card["primary"]) == 72


# ---------------------------------------------------------------------------
# Gesture rendering (128×128 @ 4bpp budget)
# ---------------------------------------------------------------------------

def test_render_gesture_is_128px():
    pytest.importorskip("PIL")
    from dreamlayer.dream_mode.sprite_bridge import GESTURE_SIZE, render_gesture
    img = render_gesture(sprite_from_phrase("ordinary miracle"))
    assert img.size == (GESTURE_SIZE, GESTURE_SIZE)


def test_render_gesture_4bpp_budget():
    """128×128 @ 4bpp = 8192 bytes of pixel data — half the 256px budget
    and comfortably inside the documented ~8KB sprite ceiling."""
    pytest.importorskip("PIL")
    from dreamlayer.dream_mode.sprite_bridge import render_gesture
    img = render_gesture(sprite_from_phrase("patient silence"))
    quantized = img.quantize(colors=16)
    assert len(quantized.tobytes()) // 2 <= 8192


def test_render_gesture_draws_in_dominant_color():
    pytest.importorskip("PIL")
    from dreamlayer.dream_mode.sprite_bridge import render_gesture
    sprite = GesturalSprite(dominant=0x00FF00, shapes=[
        {"kind": "circle", "x": 64, "y": 64, "size": 40},
        {"kind": "line", "x": 64, "y": 100, "size": 40},
        {"kind": "rect", "x": 64, "y": 30, "size": 30},
    ])
    img = render_gesture(sprite)
    assert (0, 255, 0) in {c for _, c in img.getcolors(100000)}


# ---------------------------------------------------------------------------
# Bridge anchoring (SynesthesiaCard v2 sprite is the display's bottom half)
# ---------------------------------------------------------------------------

def test_sprite_bridge_flush_sends_anchor():
    from dreamlayer.dream_mode import sprite_bridge as sb

    class FakeBridge:
        def __init__(self): self.sent = []
        def send_raw(self, obj): self.sent.append(obj)

    bridge = FakeBridge()
    b = sb.SpriteBridge(bridge)
    b._pending = (b"payload", "sprite", 64, 128)   # bypass brilliant-msg dep
    asyncio.run(b.flush_pending())
    assert bridge.sent == [{"t": "sprite", "data": b"payload", "x": 64, "y": 128}]
