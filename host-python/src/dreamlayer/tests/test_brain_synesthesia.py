"""Synesthesia — the scene as six words.

Filed for most of this audit as "needs a phone IMU feed", because the demo
catalogue titles it "Your inner weather" and there is a real IMU/biometric lens
called Inner Weather. The BUILDER says otherwise: `synesthesia_card(description,
confidence)`, docstring "VLM 6-word poetic scene description". No IMU is
involved. It is a caption, and the Brain has had a vision seam the whole time
(`WorldLensHost._describe`, already used by the structured recognizer and
already egress-gated).

Fifth card in this audit whose "blocker" was me reading its title instead of its
signature. The others were TimeScrubNode, ProactiveMemory, CommitmentRecall and
AnswerAhead.

Most of what is tested here is the NORMALISER, because an instruction-tuned
model asked for six words returns six words most of the time and returns
"Sure! Here's a phrase:" the rest of it — and `synesthesia_card` clips at 72
characters, so unhandled noise becomes a sentence truncated mid-word on the
glass, which reads as a bug rather than as a poem.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server import world_lens as W
from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


# --- the normaliser ----------------------------------------------------------

class TestSixWords:

    @pytest.mark.parametrize("raw,want", [
        ("rain beading on cold glass", "rain beading on cold glass"),
        ("Sure! Here's a phrase: rain on glass", "rain on glass"),
        ("Phrase: rain on glass", "rain on glass"),
        ('"quiet light through dusty blinds"', "quiet light through dusty blinds"),
        ("morning fog over still water.", "morning fog over still water"),
        ("1. rain on glass\n2. something else", "rain on glass"),
        ("- rain on glass", "rain on glass"),
        ("", ""),
        ("   ", ""),
    ])
    def test_it_folds_a_models_reply_into_a_phrase(self, raw, want):
        assert W._six_words(raw) == want

    def test_a_long_reply_is_truncated_not_rejected(self):
        """The first six words of a longer phrase is still usable; silence for
        want of exact obedience means reporting nothing on a working model."""
        out = W._six_words("A long reply that goes on and on past six words")
        assert len(out.split()) == W.SYNESTHESIA_MAX_WORDS
        assert out.startswith("A long reply")

    def test_a_clock_time_survives_the_preamble_stripper(self):
        """The naive version ate an hour: "6:15 to Brighton" became "15 to
        Brighton". A preamble is multi-word or a known lead word, never a bare
        number."""
        assert W._six_words("6:15 to Brighton") == "6:15 to Brighton"
        assert W._six_words("7:30 light on the platform") == "7:30 light on the platform"

    def test_the_word_cap_matches_what_the_card_can_draw(self):
        """`synesthesia_card` clips at 72 chars and renders one hero line. Six
        short words fit; the cap exists to keep them fitting."""
        from dreamlayer.hud import cards
        phrase = W._six_words("rain beading slowly on the coldest glass")
        card = cards.synesthesia_card(phrase)
        assert card["primary"] == phrase
        assert len(card["primary"]) <= 72


# --- the lens ----------------------------------------------------------------

class _Vision:
    """A backend with a vision model, answering a fixed reply."""

    def __init__(self, reply="rain beading on cold glass"):
        self.reply = reply
        self.prompts = []

    def describe(self, prompt, image_b64):
        self.prompts.append({"prompt": prompt, "had_image": bool(image_b64)})
        return self.reply


def _frame():
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    return np.full((48, 48, 3), 120, dtype="uint8")


class TestTheLens:

    def _wl(self, brain, backend):
        brain._backend = backend
        wl = brain.world_lens()
        return wl

    def test_it_asks_the_vision_model_with_the_frame(self, brain):
        vis = _Vision()
        wl = self._wl(brain, vis)
        out = wl.look_lens(_frame(), "synesthesia")
        assert out["ok"] is True
        assert out["description"] == "rain beading on cold glass"
        assert vis.prompts and vis.prompts[0]["had_image"] is True
        assert "six words" in vis.prompts[0]["prompt"]

    def test_no_vision_model_self_describes_instead_of_erroring(self, brain):
        """Every frontier lens is reachable and says what it needs. This one is
        NOT gated by a pack — it needs a configured vision model, which no
        capability key describes — so it says that instead of naming a pack
        that would not help."""
        class _Blind:
            pass
        wl = self._wl(brain, _Blind())
        out = wl.look_lens(_frame(), "synesthesia")
        assert out["ok"] is False
        assert out["reason"] == "no-vision-model"
        assert "ollama_vision_model" in out["note"]

    def test_the_guard_is_a_call_not_a_bound_method(self, brain):
        """`has_vision` is a METHOD. `if not self._router.has_vision` is a bound
        method and always truthy, so the guard silently never fired — a Brain
        with no vision model fell through to an empty description instead of
        saying what it needed. Caught by the test above; pinned here."""
        import inspect
        src = inspect.getsource(W.WorldLensHost.look_lens)
        assert "self._router.has_vision()" in src
        assert "not self._router.has_vision:" not in src

    def test_a_veiled_look_is_blind(self, brain):
        wl = self._wl(brain, _Vision())
        brain.config.network_mode = "lan_only"
        out = wl.look_lens(_frame(), "synesthesia")
        assert out["ok"] is False and out.get("veiled") is True

    def test_a_model_that_declines_is_a_miss_not_a_card(self, brain):
        """`_describe` returns "" when the posture blocks remote vision, when
        there is no model, and when the model declines. All three mean "no
        description", and none should draw a card saying so."""
        wl = self._wl(brain, _Vision(reply="   "))
        out = wl.look_lens(_frame(), "synesthesia")
        assert out["ok"] is False and out["description"] == ""

    def test_it_is_registered_as_a_real_lens(self, brain):
        assert "synesthesia" in W.WorldLensHost._LENS_NEEDS


# --- the card ----------------------------------------------------------------

class TestTheCard:

    def test_a_look_through_the_lens_draws_the_phrase(self, brain):
        """The gap this closes: every other frontier lens returns fields the
        Live Lens renders from JSON, so a phrase with no card is a string in a
        network response. `synesthesia_card` had no caller at all."""
        from dreamlayer.ai_brain.server import live as live_mod
        brain._backend = _Vision()
        seen = _pushes(brain)
        np = pytest.importorskip("numpy")
        pytest.importorskip("PIL")
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(np.full((48, 48, 3), 120, dtype="uint8")).save(buf, format="JPEG")
        out = live_mod.look(brain, buf.getvalue(), lens="synesthesia")
        assert out.get("ok") is True, out
        kind, card = seen[-1]
        assert kind == "synesthesia" and card["type"] == "SynesthesiaCard"
        assert card["primary"] == "rain beading on cold glass"
        assert card["eyebrow"] == "DREAM"

    def test_an_empty_phrase_pushes_nothing(self, brain):
        from dreamlayer.ai_brain.server import live as live_mod
        brain._backend = _Vision(reply="")
        seen = _pushes(brain)
        np = pytest.importorskip("numpy")
        pytest.importorskip("PIL")
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(np.full((48, 48, 3), 120, dtype="uint8")).save(buf, format="JPEG")
        live_mod.look(brain, buf.getvalue(), lens="synesthesia")
        assert not [c for k, c in seen if k == "synesthesia"]

    def test_the_live_lens_draws_it_rather_than_the_generic_fallback(self):
        """The generic renderer nearly gets this one right, and "nearly" is the
        problem — it stamps its own JUNO eyebrow over the card's DREAM."""
        import pathlib
        src = (pathlib.Path(W.__file__).parent / "live.py").read_text(encoding="utf-8")
        assert 'else if (t === "SynesthesiaCard") glassSynesthesiaCard(c);' in src
        i = src.index("function glassSynesthesiaCard")
        body = src[i:i + 1400]
        assert "c.description" in body and "DREAM" in body
