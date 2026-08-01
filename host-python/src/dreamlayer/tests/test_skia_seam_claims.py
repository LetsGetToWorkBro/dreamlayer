"""`hud/render_skia.py` claimed to plug into a hook it does not fit.

Its docstring said it "exposes it behind the SAME `fn(card)->PIL.Image` shape
`CardRenderer.register(card_type, fn)` already accepts, so it wires in with zero
core edits". Both halves were wrong, and following them breaks the HUD:

  1. `register`'s callback is `fn(draw, card)` — two arguments, drawing onto an
     existing canvas. `make_skia_renderer` returns a ONE-argument function, so
     `render()` raises TypeError on the first card of that type.
  2. `_skia_blank` clears to black and writes `card["title"]`, a key HUD cards
     do not carry. Even with the arity fixed it would replace every working card
     with a black square — under the floor this repo already holds an optional
     dependency to: never return less than its own fallback.

The rasterizing half is real, so the module stays. What changed is that it now
says what it is, and these tests keep the claims and the code together.
"""
from __future__ import annotations

import pathlib

import pytest

from dreamlayer.hud.render_skia import available, make_skia_renderer
from dreamlayer.hud.renderer import CardRenderer


class TestTheMismatchIsRealAndStaysDocumented:
    def test_registering_it_as_documented_raises(self):
        """The exact call the old docstring prescribed."""
        r = CardRenderer()
        r.register("SavedMemoryCard", make_skia_renderer(lambda card: None))
        with pytest.raises(TypeError, match="positional argument"):
            r.render({"type": "SavedMemoryCard", "primary": "Held."})

    def test_the_register_hook_really_is_two_argument(self):
        """Pinned from the other side, so a change to EITHER surface shows up
        here rather than in a builder's broken HUD."""
        r = CardRenderer()
        seen = []
        r.register("SavedMemoryCard", lambda draw, card: seen.append(card))
        r.render({"type": "SavedMemoryCard", "primary": "Held."})
        assert seen and seen[0]["primary"] == "Held."

    def test_the_module_no_longer_claims_it_fits(self):
        from dreamlayer.hud import render_skia
        src = pathlib.Path(render_skia.__file__).read_text(encoding="utf-8")
        # the old promise is quoted in the correction, so check the SIGNATURE
        # docstring rather than the file — that is where a builder looks
        assert "NOT a `CardRenderer.register` callback" in (
            render_skia.make_skia_renderer.__doc__ or "")
        assert "Not a card renderer, and not\nregisterable as one." in src

    def test_the_fallback_still_holds_the_floor(self):
        """Whatever else is true, the no-skia path must return exactly what the
        PIL renderer would — that is the one promise worth keeping."""
        sentinel = object()
        fn = make_skia_renderer(lambda card: sentinel)
        if available:                       # pragma: no cover - env dependent
            pytest.skip("skia installed; the fallback path is not the one taken")
        assert fn({"type": "SavedMemoryCard"}) is sentinel

    def test_the_stub_draw_is_named_as_a_stub(self):
        """`_skia_blank` reads `title`, which no HUD card carries. It is kept as
        a demonstration, and the docstring has to keep saying so — a future
        reader wiring it up is the failure this file exists to prevent."""
        from dreamlayer.hud import render_skia
        assert "demonstration" in (render_skia._skia_blank.__doc__ or "")
        from dreamlayer.hud import cards
        built = cards.saved_memory("Held.")
        assert "title" not in built, (
            "a HUD card grew a `title` — the stub's assumption may now hold, "
            "which would make it worth finishing rather than documenting")
