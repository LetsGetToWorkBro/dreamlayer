"""Paint layer — the bounded vector-stroke "draw on your lens" surface.

A GlyphSpec is pure decoration: a polyline in normalized display coordinates,
one palette color, one width token. It carries no clock and emits nothing, so
the proof envelope needs only count/vertex/coordinate caps. These tests pin
that the caps are enforced, the layer round-trips through canonical JSON and
the signature, and the interpreter surfaces the strokes to the renderer.
"""
import pytest

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, GlyphSpec, Transition, Stage, verify, END,
)
from dreamlayer.reality_compiler.v2.figment import MAX_GLYPHS, MAX_GLYPH_POINTS


def _painted(glyphs) -> Figment:
    fig = Figment(name="Painted", initial="a")
    fig.add_scene(Scene(
        id="a", duration_sec=5.0, tick="countdown",
        lines=[TextLine("HI", row=0, size="lg")],
        on_timeout=[Transition(target=END)],
        glyphs=glyphs,
    ))
    return fig


def _stroke(**kw) -> GlyphSpec:
    kw.setdefault("points", [(0.2, 0.2), (0.8, 0.8)])
    return GlyphSpec(**kw)


class TestBudget:
    def test_a_simple_stroke_verifies(self):
        assert verify(_painted([_stroke()])).ok

    def test_up_to_the_cap_verifies(self):
        assert verify(_painted([_stroke() for _ in range(MAX_GLYPHS)])).ok

    def test_too_many_strokes_rejected(self):
        rep = verify(_painted([_stroke() for _ in range(MAX_GLYPHS + 1)]))
        assert not rep.ok and any(v.code == "glyphs" for v in rep.violations)

    def test_single_point_stroke_rejected(self):
        rep = verify(_painted([_stroke(points=[(0.5, 0.5)])]))
        assert not rep.ok and any(v.code == "glyph_points" for v in rep.violations)

    def test_too_many_points_rejected(self):
        pts = [(i / (MAX_GLYPH_POINTS + 2), 0.5) for i in range(MAX_GLYPH_POINTS + 1)]
        rep = verify(_painted([_stroke(points=pts)]))
        assert not rep.ok and any(v.code == "glyph_points" for v in rep.violations)

    def test_off_display_coordinate_rejected(self):
        rep = verify(_painted([_stroke(points=[(0.5, 0.5), (1.4, 0.5)])]))
        assert not rep.ok and any(v.code == "glyph_coord" for v in rep.violations)

    def test_non_palette_color_rejected(self):
        rep = verify(_painted([_stroke(color="#ff00ff")]))
        assert not rep.ok and any(v.code == "color" for v in rep.violations)

    def test_unknown_width_rejected(self):
        rep = verify(_painted([_stroke(width="xl")]))
        assert not rep.ok and any(v.code == "glyph_width" for v in rep.violations)

    def test_paint_adds_no_emit_or_display_cost(self):
        rep = verify(_painted([_stroke() for _ in range(MAX_GLYPHS)]))
        # strokes are static — no autonomous emits, display stays the 1Hz baseline
        assert rep.worst_emit_per_sec == 0.0
        assert rep.worst_display_hz == 1.0


class TestRoundTrip:
    def test_canonical_json_round_trips_the_strokes(self):
        fig = _painted([_stroke(points=[(0.1, 0.9), (0.5, 0.1), (0.9, 0.9)],
                                color="accent_memory", width="lg")])
        again = Figment.from_dict(fig.to_dict())
        g = again.scenes["a"].glyphs[0]
        assert g.color == "accent_memory" and g.width == "lg"
        assert g.points == [(0.1, 0.9), (0.5, 0.1), (0.9, 0.9)]
        # byte-stable — the strokes are part of what gets signed
        assert again.canonical_json() == fig.canonical_json()

    def test_coordinates_are_rounded_for_signature_stability(self):
        fig = _painted([_stroke(points=[(0.123456789, 0.5), (0.9, 0.5)])])
        d = fig.to_dict()["scenes"]["a"]["glyphs"][0]
        assert d["points"][0][0] == round(0.123456789, 4)

    def test_a_scene_without_paint_omits_the_key(self):
        fig = Figment(name="Plain", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=1.0,
                            on_timeout=[Transition(target=END)]))
        assert "glyphs" not in fig.to_dict()["scenes"]["a"]


class TestInterpreter:
    def test_frame_surfaces_the_strokes_to_the_renderer(self):
        fig = _painted([_stroke(points=[(0.2, 0.2), (0.8, 0.8)], color="accent_success")])
        st = Stage(fig)
        frame = st.frame()
        assert len(frame.glyphs) == 1
        assert frame.glyphs[0].color == "accent_success"
        assert frame.glyphs[0].points[0] == (0.2, 0.2)
