"""Dream Mode's scene layer on the Live Lens — the REAL primitives.

Every assertion runs the genuine SceneDescriber + GhostLayer: the frame → a
SynesthesiaCard (phrase + three-shape gesture), a saved place → a memory-echo
ghost, and the wearer's veil silencing both. The Brain is only the meeting
point between this phone's camera and its own vision; nothing here is faked and
nothing is persisted.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.live_dream import LiveDream, dream, _has_vision
from dreamlayer.ai_brain.server.store import BrainConfig

TOKEN = "rune-birch"
FRAME = b"a-nonempty-jpeg-stand-in"       # has_camera() only checks len > 0


def _brain(tmp_path, **cfg) -> Brain:
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token=TOKEN, **cfg).save(d)
    return Brain(d)


class TestScene:
    def test_offline_scene_is_an_honest_synesthesia_card(self, tmp_path):
        # no vision backend → SceneDescriber's documented fallback (a poetic
        # mood + a hash-derived gesture), never a blank and never a fabricated
        # literal description
        brain = _brain(tmp_path)
        assert _has_vision(brain) is False
        out = dream(brain).scene(FRAME)
        scene = out["scene"]
        assert scene and scene["type"] == "SynesthesiaCard" and scene["version"] == 2
        assert scene["description"]                      # a phrase
        assert len(scene["shapes"]) == 3                 # the gestural sprite
        assert "dominant_color" in scene

    def test_veil_returns_no_scene_and_no_ghost(self, tmp_path):
        brain = _brain(tmp_path, network_mode="lan_only")   # incognito_now() True
        brain.waypath.remember_place("keys", "the hallway bowl")
        out = dream(brain).scene(FRAME)
        assert out == {"scene": None, "ghost": None}        # deaf and blind

    def test_empty_frame_yields_no_scene(self, tmp_path):
        # has_camera() is False for an empty body → the describer returns None
        out = dream(_brain(tmp_path)).scene(b"")
        assert out["scene"] is None


class TestNeverIdentifies:
    """The dream never names a stranger — the product's hardest privacy rule,
    enforced on the synesthesia phrase through the same person_guard every
    world-lens surface uses."""

    def test_a_named_person_is_reduced_to_a_nameless_line(self, tmp_path):
        from dreamlayer.ai_brain.server.live_dream import _NAMELESS_MOOD
        ld = LiveDream(_brain(tmp_path))
        named = {"type": "SynesthesiaCard", "version": 2,
                 "description": "Alice Chen laughing beneath golden oak",
                 "primary": "Alice Chen laughing beneath golden oak",
                 "dominant_color": 0x2CC79A,
                 "shapes": [{"kind": "circle", "x": 1, "y": 2, "size": 10}] * 3}
        out = ld._guard_identity(named)
        assert out["description"] == _NAMELESS_MOOD          # the name is gone
        assert "Alice" not in out["primary"] and "Chen" not in str(out)
        assert len(out["shapes"]) == 3                        # the gesture survives

    def test_an_abstract_phrase_passes_through_untouched(self, tmp_path):
        ld = LiveDream(_brain(tmp_path))
        safe = {"type": "SynesthesiaCard", "version": 2,
                "description": "soft light still breathing here",
                "dominant_color": 1, "shapes": []}
        assert ld._guard_identity(safe)["description"] == "soft light still breathing here"

    def test_the_prompt_forbids_naming_a_person(self):
        from dreamlayer.dream_mode.scene_describer import _POETIC_PROMPT
        assert "identify any person" in _POETIC_PROMPT.lower() \
            or "name" in _POETIC_PROMPT.lower()


class TestGhost:
    def test_saved_place_surfaces_a_memory_echo(self, tmp_path):
        brain = _brain(tmp_path)
        brain.waypath.remember_place("bike", "the north rack")
        out = dream(brain).scene(FRAME)
        ghost = out["ghost"]
        assert ghost and ghost["eyebrow"] == "MEMORY ECHO"
        assert "bike" in ghost["summary"]                # the REAL saved subject
        assert "north rack" in (ghost.get("detail") or "")
        assert ghost["opacity"] == 0.20                  # the device's dim ghost

    def test_no_saved_places_no_ghost(self, tmp_path):
        # a fresh Brain has nothing kept — no ghost is invented
        out = dream(_brain(tmp_path)).scene(FRAME)
        assert out["ghost"] is None

    def test_same_anchor_is_debounced(self, tmp_path):
        brain = _brain(tmp_path)
        brain.waypath.remember_place("umbrella", "by the door")
        d = dream(brain)
        assert d.scene(FRAME)["ghost"] is not None        # first surfaces
        assert d.scene(FRAME)["ghost"] is None            # cooldown holds (120 s)


class TestCaching:
    def test_layer_is_cached_on_the_brain(self, tmp_path):
        brain = _brain(tmp_path)
        assert dream(brain) is dream(brain)               # one per Brain
        assert isinstance(brain._live_dream, LiveDream)


class TestPageShipsDreamScene:
    def test_scene_beat_and_renderers_ship(self):
        from dreamlayer.ai_brain.server.live import render_live
        page = render_live()
        for n in ("function dreamSceneBeat", "function drawSynesthesia",
                  "function drawGhost", "/dreamlayer/live/dream/scene",
                  "MEMORY ECHO", "SCENE_MS"):
            assert n in page, f"dream-scene piece missing: {n}"
