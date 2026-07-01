"""Figment IR: construction, serialization, canonical stability."""
import pytest

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, PulseSpec, CounterDecl, CounterOp,
    Guard, Transition, FigmentError, END,
)


def make_timer() -> Figment:
    fig = Figment(name="Timer", initial="armed")
    armed = fig.add_scene(Scene(id="armed", lines=[
        TextLine("READY", row=1, size="lg")]))
    armed.on["double"] = Transition(target="run")
    fig.add_scene(Scene(
        id="run", duration_sec=180.0, tick="countdown",
        lines=[TextLine("{remaining}", row=1, size="lg")],
        pulse=PulseSpec(window_sec=10, color="accent_attention", rate_hz=2.0),
        on_timeout=[Transition(target=END)],
    ))
    return fig


class TestConstruction:
    def test_duplicate_scene_raises(self):
        fig = Figment(name="x", initial="a")
        fig.add_scene(Scene(id="a"))
        with pytest.raises(FigmentError, match="duplicate scene"):
            fig.add_scene(Scene(id="a"))

    def test_duplicate_counter_raises(self):
        fig = Figment(name="x", initial="a")
        fig.add_counter(CounterDecl("n"))
        with pytest.raises(FigmentError, match="duplicate counter"):
            fig.add_counter(CounterDecl("n"))

    def test_ids_are_unique(self):
        assert make_timer().id != make_timer().id


class TestSerialization:
    def test_roundtrip(self):
        fig = make_timer()
        fig.add_counter(CounterDecl("round", start=1, lo=1, hi=8))
        fig.scenes["run"].on_timeout = [
            Transition(target=END, when=Guard("round", "ge", 8)),
            Transition(target="run",
                       counter_ops=[CounterOp("round", "inc", 1)],
                       emit="lap"),
        ]
        back = Figment.from_dict(fig.to_dict())
        assert back.canonical_json() == fig.canonical_json()

    def test_canonical_is_stable(self):
        fig = make_timer()
        assert fig.canonical_json() == fig.canonical_json()
        # canonical form is compact and sorted — signature-stable
        assert " " not in fig.canonical_json().split('"content"')[0]

    def test_canonical_changes_when_content_changes(self):
        a, b = make_timer(), make_timer()
        b.id = a.id
        before = b.canonical_json()
        b.scenes["run"].duration_sec = 181.0
        assert b.canonical_json() != before
        assert a.canonical_json() != b.canonical_json()


class TestDescribe:
    def test_describe_is_plain_words(self):
        text = make_timer().describe()
        assert "Timer" in text
        assert "180s" in text
        assert "pulse last 10s" in text
        assert "on double → run" in text
