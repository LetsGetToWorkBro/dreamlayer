"""test_brain_card_producers.py — the Brain draws, not only answers.

`scripts/hud_reachability.py` found 18 of 24 declared HUD cards with no
Brain-side producer: the builder exists, `halo-lua` has a drawing for it, the
demo film shows it, and nothing a shipped Brain can reach ever calls it. That is
`decisions/0001` at the card layer — "where did I leave my keys" came back as
JSON and the glass stayed blank.

Three of them close here, and each test asserts what the WIRE carries rather
than that a function ran, because the interesting failures are all in the
payload:

  * ObjectRecallCard — the answer is in `place`, not `primary`. A hand-rolled
    lookalike passes a shape check and renders blank.
  * SavedMemoryCard — the confirmation must NOT quote the thought it kept.
  * JunoReplyCard — it must push the ANSWER, never the caller's question.

The other 15 are deliberately still open; `test_reachability_checkers.py` holds
the count, and the reasons are in HANDOFF §3.

ONE THING THIS FILE ASSUMES AND `test_reachability_checkers.py` PROVES: a Brain
push lands on the Live Lens (`live.py`), not on `halo-lua`. Nothing under
`ai_brain/` calls `bridge.send_card`. So "halo-lua draws this type" is not
evidence a wearer sees anything.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# ObjectRecallCard — "where did I leave my bike"
# ---------------------------------------------------------------------------

class TestWhereYouLeftIt:

    def test_a_found_locate_draws_the_card(self, brain):
        brain.waypath_stash("bike", "the north rack")
        q = brain.subscribe_events()
        out = brain.waypath_locate("bike")

        assert out["pushed"] == 1, out
        ev = q.get_nowait()
        assert ev["kind"] == "object_recall"
        assert ev["safety"] is False
        assert ev["card"]["type"] == "ObjectRecallCard"

    def test_the_answer_rides_in_place_not_primary(self, brain):
        """The assertion that catches the plausible wrong version.

        `object_recall()` puts the object in `primary` and THE PLACE — the whole
        answer — in `place`. A hand-rolled `{"primary": subject, "detail": text}`
        would satisfy any shape check and render "bike" with no answer, because
        both renderers read `place` as the hero. This is the `_drift_card`
        mistake (`lens_hosts.py`) reproduced as a test.
        """
        brain.waypath_stash("bike", "the north rack")
        q = brain.subscribe_events()
        brain.waypath_locate("bike")
        card = q.get_nowait()["card"]

        assert card["place"] == "the north rack"
        assert card["object"] == "bike"

    def test_the_place_is_not_also_printed_as_detail(self, brain):
        """Brain-side anchors are place-only, so the cue text is literally
        "at <place>". Passing it as `detail` prints the answer twice at two
        different clip widths."""
        brain.waypath_stash("bike", "the north rack")
        q = brain.subscribe_events()
        brain.waypath_locate("bike")
        assert q.get_nowait()["card"]["detail"] == ""

    def test_confidence_is_stated_rather_than_left_to_default(self, brain):
        """`None` is not neutral on the glass — the renderer initialises the
        confidence arc to MEDIUM and only overrides it when a value is present,
        so omitting it renders a hedge the Brain never expressed."""
        brain.waypath_stash("bike", "the north rack")
        q = brain.subscribe_events()
        brain.waypath_locate("bike")
        assert q.get_nowait()["card"]["confidence"] == 0.9

    def test_a_placeless_anchor_pushes_nothing(self, brain):
        """`waypath_stash` accepts an empty place, and the cue then reads
        "somewhere you saved it" — with the card's hero slot blank. Better no
        card than a card with a hole where the answer goes."""
        brain.waypath_stash("kite", "")
        q = brain.subscribe_events()
        out = brain.waypath_locate("kite")

        assert out["found"] is True and out["pushed"] == 0, out
        assert q.empty()

    def test_a_missing_anchor_pushes_nothing(self, brain):
        q = brain.subscribe_events()
        out = brain.waypath_locate("something never stashed")
        assert out["found"] is False
        assert q.empty()

    def test_the_stored_subject_is_drawn_not_the_callers_string(self, brain):
        """`locate` matches on a substring, so the wearer's words and the stored
        anchor can differ — and only the anchor is ours to draw."""
        brain.waypath_stash("bike", "the north rack")
        q = brain.subscribe_events()
        brain.waypath_locate("my bike please")
        assert q.get_nowait()["card"]["object"] == "bike"


# ---------------------------------------------------------------------------
# SavedMemoryCard — a held thought pinned
# ---------------------------------------------------------------------------

class TestKeepAMoment:

    def _held(self, brain):
        ls = brain.lenses()
        ls.ingest_utterance("the deposit needs paying before Friday", via="said")
        r = ls.freeze()
        return ls, r["id"]

    def test_pinning_confirms_on_the_glass(self, brain):
        ls, fid = self._held(brain)
        q = brain.subscribe_events()
        assert ls.pin(fid) is True

        ev = q.get_nowait()
        assert ev["kind"] == "saved_memory"
        assert ev["safety"] is False
        assert ev["card"] == {"type": "SavedMemoryCard", "dismiss_ms": 1200,
                              "primary": "Held.", "lines": ["Held."]}

    def test_the_confirmation_never_quotes_what_it_kept(self, brain):
        """The standing rule, as an assertion. A confirmation that repeats the
        held sentence would push captured speech over the event stream — the
        exact thing the ear's redaction exists to prevent. `Held.` is the whole
        payload, and that is not an oversight."""
        ls, fid = self._held(brain)
        q = brain.subscribe_events()
        ls.pin(fid)
        assert "deposit" not in repr(q.get_nowait())

    def test_pinning_twice_does_not_flash_twice(self, brain):
        """`/dreamlayer/stasis/pin` is a plain POST; nothing stops a client
        sending it again. A second confirmation for a moment already kept is
        noise on the glass."""
        ls, fid = self._held(brain)
        ls.pin(fid)
        q = brain.subscribe_events()
        assert ls.pin(fid) is True
        assert q.empty()


# ---------------------------------------------------------------------------
# JunoReplyCard — the answer, drawn
# ---------------------------------------------------------------------------

class TestAskItAnything:

    def _voice(self, brain, text, answer="Canberra."):
        from dreamlayer.ai_brain.server.backends import Answer
        brain.ask = lambda q, no_cloud=False: Answer(  # type: ignore[method-assign]
            text=answer, tier="device", sources=[], confidence=0.8)
        from dreamlayer.orchestrator.voice import parse_intent
        it = parse_intent(text)
        assert it.kind in ("ask", "recall"), it.kind
        ans = brain.ask(it.args.get("query", ""))
        out = {"intent": it.kind, "answer": ans.text}
        reply = out["answer"].strip()
        if reply:
            from dreamlayer.hud import cards
            out["pushed"] = brain.push_event(
                "juno", cards.juno_reply(reply[:160], "answer"), veil_ok=False)
        return out

    def test_the_answer_is_drawn(self, brain):
        q = brain.subscribe_events()
        out = self._voice(brain, "what is the capital of australia")

        assert out["pushed"] == 1
        ev = q.get_nowait()
        assert ev["kind"] == "juno"
        assert ev["safety"] is False
        assert ev["card"]["type"] == "JunoReplyCard"
        assert ev["card"]["primary"] == "Canberra."
        assert ev["card"]["eyebrow"] == "JUNO"

    def test_it_draws_the_answer_not_the_question(self, brain):
        """The mistake worth a test: pushing the caller's own string would turn
        this route into an arbitrary-text-onto-every-glass primitive."""
        q = brain.subscribe_events()
        self._voice(brain, "what is the capital of australia")
        assert q.get_nowait()["card"]["primary"] != "what is the capital of australia"

    def test_the_reply_carries_no_alert_signals(self, brain):
        """Only a safety tap gets a sound. A reply that borrowed an earcon would
        read as an alarm."""
        q = brain.subscribe_events()
        self._voice(brain, "what is the capital of australia")
        card = q.get_nowait()["card"]
        for k in ("earcon", "haptic", "flash"):
            assert k not in card, k

    def test_an_empty_answer_pushes_nothing(self, brain):
        q = brain.subscribe_events()
        out = self._voice(brain, "what is the capital of australia", answer="")
        assert "pushed" not in out
        assert q.empty()


# ---------------------------------------------------------------------------
# The veil, over all three at once
# ---------------------------------------------------------------------------

class TestTheGlassGoesDarkUnderTheShield:

    def test_no_card_is_pushed_while_incognito(self, brain, monkeypatch):
        """All three are ambient pushes — none is a safety alert — so all three
        must be suppressed. And the phone must still ANSWER: the divergence
        worth knowing about is that under the shield the wearer still hears the
        reply while the glass stays dark."""
        brain.waypath_stash("bike", "the north rack")
        ls = brain.lenses()
        ls.ingest_utterance("the deposit needs paying", via="said")
        fid = ls.freeze()["id"]

        monkeypatch.setattr(brain, "incognito_now", lambda: True)
        q = brain.subscribe_events()

        out = brain.waypath_locate("bike")
        assert out["pushed"] == 0
        assert out["say"], "the answer itself must survive the veil"
        ls.pin(fid)
        from dreamlayer.hud import cards
        assert brain.push_event("juno", cards.juno_reply("Canberra.")) == 0

        assert q.empty()

    def test_an_unreadable_posture_is_treated_as_veiled(self, brain, monkeypatch):
        def _boom():
            raise RuntimeError("posture unreadable")
        brain.waypath_stash("bike", "the north rack")
        monkeypatch.setattr(brain, "incognito_now", _boom)
        q = brain.subscribe_events()
        assert brain.waypath_locate("bike")["pushed"] == 0
        assert q.empty()
