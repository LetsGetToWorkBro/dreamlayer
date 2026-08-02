"""The bar the wearer's own swats set — `persona_tuning`, reachable at last.

`persona_tuning` was wired in #598 to `MaturityGate.tuned_confidence`, and
`MaturityGate` is constructed at exactly one site: `orchestrator.py`. Per
`decisions/0001` the shipped Brain never builds an `Orchestrator`, and
`test_the_orchestrator_is_still_not_resurrected` keeps it that way. So the
tuning ran in tests and in the simulator and nowhere the wearer could reach —
the exact `importable != constructed != called != reachable` failure this repo
keeps finding, committed by the fix for it.

`attention_live` re-hosts the plain half Brain-side, following the precedent
`retention_live.py` set rather than resurrecting the Orchestrator. These tests
pin the three things that make it a capability rather than a claim: the label
crosses back from the glass, the bar is fit from those labels, and
`push_event` — the single funnel every card goes through — actually consults it.
"""
from __future__ import annotations

import json

import pytest

from dreamlayer.ai_brain.server.attention_live import (
    BAR_CEILING, LOG_MAX, MIN_LABELLED, AttentionGate, _above_confidence,
)


def _teach(gate, n=40, split=0.80, lo=0.50, hi=1.0, seed=5):
    """A wearer who swats the unsure cards and tolerates the confident ones."""
    import random
    rnd = random.Random(seed)
    for _ in range(n):
        conf = round(rnd.uniform(lo, hi), 2)
        gate.observe("candor", conf, dismissed=conf < split)
    return gate


class TestTheFloor:
    """No history must never mean worse than the behaviour it replaced."""

    def test_a_fresh_gate_suppresses_nothing(self):
        g = AttentionGate()
        assert g.bar() == 0.0
        assert g.allows("candor", 0.01) is True
        assert g.allows("candor", 0.0) is True

    def test_too_few_labels_is_not_a_bar(self):
        g = AttentionGate()
        _teach(g, n=MIN_LABELLED - 1)
        assert g.bar() == 0.0
        assert g.allows("candor", 0.1) is True

    def test_a_card_with_no_confidence_is_never_gated(self):
        # Absence is not low. Most card builders pass `confidence=None`, and
        # gating those would silence the majority of the HUD on a bar that was
        # never about them.
        g = _teach(AttentionGate())
        assert g.bar() > 0.0
        assert g.allows("candor", None) is True

    def test_it_fails_open(self):
        class _Broken(AttentionGate):
            def bar(self):
                raise RuntimeError("tuning exploded")
        g = _Broken()
        assert g.allows("candor", 0.0) is True, (
            "an unreadable PREFERENCE must not silence the glass — that is the "
            "Veil's job and the Veil fails the other way")

    def test_nan_is_not_a_verdict(self):
        g = _teach(AttentionGate())
        assert g.allows("candor", float("nan")) is True
        assert g.observe("candor", float("nan"), True) is False


class TestTheBar:
    def test_it_recovers_the_split_the_wearer_taught(self):
        g = _teach(AttentionGate(), split=0.80)
        assert g.bar() == pytest.approx(0.80)

    def test_a_surer_wearer_gets_a_higher_bar(self):
        assert _teach(AttentionGate(), split=0.90).bar() > \
            _teach(AttentionGate(), split=0.60).bar()

    def test_it_gates_on_the_learned_bar(self):
        g = _teach(AttentionGate(), split=0.80)
        assert g.allows("candor", 0.95) is True
        assert g.allows("candor", 0.55) is False

    def test_a_wearer_who_swats_everything_gets_no_bar(self):
        # One label. Confidence does not explain this behaviour, and drawing a
        # threshold anyway would be a coincidence with a number on it.
        g = AttentionGate()
        for i in range(40):
            g.observe("candor", 0.5 + (i % 5) / 10.0, dismissed=True)
        assert g.bar() == 0.0

    def test_a_wearer_who_keeps_everything_gets_no_bar(self):
        g = AttentionGate()
        for i in range(40):
            g.observe("candor", 0.5 + (i % 5) / 10.0, dismissed=False)
        assert g.bar() == 0.0

    def test_the_bar_is_capped(self):
        # A wearer who swats all but the very surest must not be able to argue
        # the system into silence; the honest control at that point is the cue
        # switch they already have.
        g = _teach(AttentionGate(), split=0.99, lo=0.90, hi=1.0)
        assert g.bar() <= BAR_CEILING

    def test_the_fit_is_cached_until_a_new_label(self):
        g = _teach(AttentionGate())
        first = g.bar()
        calls = []
        import dreamlayer.orchestrator.persona_humanlearn as ph
        real = ph.tune
        ph.tune = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        try:
            assert g.bar() == first and not calls          # cached
            g.observe("candor", 0.99, dismissed=False)
            g.bar()
            assert calls                                   # refit
        finally:
            ph.tune = real


class TestItCannotRunAway:
    """The load-bearing one. A gate that tightens from its own output and can
    never loosen is not a preference, it is a ratchet."""

    def test_suppression_starves_the_fit_and_the_bar_unlatches(self):
        g = _teach(AttentionGate(), split=0.80)
        assert g.bar() == pytest.approx(0.80)
        # Now only above-bar cards get through, and the wearer keeps them —
        # which is what suppression MEANS. Push enough of those to roll the
        # window over.
        for _ in range(LOG_MAX):
            g.observe("candor", 0.95, dismissed=False)
        assert g.bar() == 0.0, (
            "the log went single-label and the fit must refuse — otherwise a "
            "bar can never come back down once it stops collecting evidence "
            "below itself")
        assert g.allows("candor", 0.10) is True

    def test_the_window_is_bounded(self):
        g = AttentionGate()
        for i in range(LOG_MAX * 2):
            g.observe("candor", 0.5, dismissed=bool(i % 2))
        assert g.summary()["labelled"] == LOG_MAX


class TestTheLabelCrossesBack:
    def test_observe_records_a_label(self):
        g = AttentionGate()
        assert g.observe("candor", 0.9, dismissed=True) is True
        assert g.summary() == {"labelled": 1, "swatted": 1, "bar": 0.0,
                               "fitted": False, "min_labelled": MIN_LABELLED}

    def test_a_missing_confidence_is_not_a_label(self):
        g = AttentionGate()
        assert g.observe("candor", None, dismissed=True) is False
        assert g.observe("candor", "not a number", dismissed=True) is False
        assert g.summary()["labelled"] == 0


class TestItSurvivesARestart:
    def test_the_log_persists(self, tmp_path):
        p = tmp_path / "attention.json"
        g = _teach(AttentionGate(p))
        again = AttentionGate(p)
        assert again.summary()["labelled"] == g.summary()["labelled"]
        assert again.bar() == g.bar()

    def test_a_corrupt_row_does_not_drop_the_rest(self, tmp_path):
        p = tmp_path / "attention.json"
        p.write_text(json.dumps({"labelled": [
            {"kind": "candor", "confidence": 0.9, "dismissed": False},
            {"kind": "candor", "confidence": "nope", "dismissed": True},
            "not even a dict",
            {"kind": "candor", "dismissed": True},
            {"kind": "candor", "confidence": 0.4, "dismissed": True}]}))
        assert AttentionGate(p).summary()["labelled"] == 2

    def test_a_planted_file_cannot_take_the_gate_down(self, tmp_path):
        p = tmp_path / "attention.json"
        p.write_text("{ this is not json")
        g = AttentionGate(p)
        assert g.summary()["labelled"] == 0
        assert g.allows("candor", 0.5) is True


class TestTheFunnelConsultsIt:
    """`Brain.push_event` is the single site every card passes through
    (`server.py`). If the gate is not consulted THERE it is not consulted."""

    def _brain(self, tmp_path):
        from dreamlayer.ai_brain.server.server import Brain
        b = Brain.__new__(Brain)
        b.PROACTIVE_KINDS = Brain.PROACTIVE_KINDS
        b._attention = AttentionGate(tmp_path / "attention.json")
        return b

    def test_a_below_bar_proactive_card_is_dropped(self, tmp_path, monkeypatch):
        from dreamlayer.ai_brain.server.server import Brain
        b = self._brain(tmp_path)
        _teach(b._attention, split=0.80)
        monkeypatch.setattr(Brain, "incognito_now", lambda s: False)
        monkeypatch.setattr(Brain, "_may_interrupt", lambda s, k: True)
        import threading
        b._event_lock, b._event_subs = threading.Lock(), []
        assert Brain.push_event(b, "candor", {"confidence": 0.55}) == 0

    def test_an_above_bar_card_reaches_the_fan_out(self, tmp_path, monkeypatch):
        from dreamlayer.ai_brain.server.server import Brain
        import queue
        import threading
        b = self._brain(tmp_path)
        _teach(b._attention, split=0.80)
        monkeypatch.setattr(Brain, "incognito_now", lambda s: False)
        monkeypatch.setattr(Brain, "_may_interrupt", lambda s, k: True)
        q: queue.Queue = queue.Queue(maxsize=4)
        b._event_lock, b._event_subs = threading.Lock(), [q]
        assert Brain.push_event(b, "candor", {"confidence": 0.95}) == 1

    def test_a_non_proactive_card_is_never_gated(self, tmp_path, monkeypatch):
        # A direct answer the wearer asked for is not an interruption, and a
        # bar learned from unsolicited cards has no business suppressing it.
        from dreamlayer.ai_brain.server.server import Brain
        import queue
        import threading
        b = self._brain(tmp_path)
        _teach(b._attention, split=0.80)
        monkeypatch.setattr(Brain, "incognito_now", lambda s: False)
        monkeypatch.setattr(Brain, "_may_interrupt", lambda s, k: True)
        q: queue.Queue = queue.Queue(maxsize=4)
        b._event_lock, b._event_subs = threading.Lock(), [q]
        assert "saved_memory" not in Brain.PROACTIVE_KINDS
        assert Brain.push_event(b, "saved_memory", {"confidence": 0.01}) == 1

    def test_a_safety_push_skips_the_bar(self, tmp_path, monkeypatch):
        # `veil_ok` already skips the Veil and the preferences; the softest of
        # the three gates must not be the one that stops a smoke alarm.
        from dreamlayer.ai_brain.server.server import Brain
        import queue
        import threading
        b = self._brain(tmp_path)
        _teach(b._attention, split=0.80)
        q: queue.Queue = queue.Queue(maxsize=4)
        b._event_lock, b._event_subs = threading.Lock(), [q]
        assert Brain.push_event(b, "hark", {"confidence": 0.01},
                                veil_ok=True) == 1

    def test_the_veil_still_wins(self, tmp_path, monkeypatch):
        from dreamlayer.ai_brain.server.server import Brain
        import threading
        b = self._brain(tmp_path)
        monkeypatch.setattr(Brain, "incognito_now", lambda s: True)
        b._event_lock, b._event_subs = threading.Lock(), []
        assert Brain.push_event(b, "candor", {"confidence": 1.0}) == 0


class TestThePromotionIsEarned:
    def test_an_unfit_gate_does_not_promote(self):
        assert AttentionGate().tuning_live() is False

    def test_a_refused_fit_does_not_promote(self):
        g = AttentionGate()
        for _ in range(40):
            g.observe("candor", 0.9, dismissed=True)     # one label only
        assert g.tuning_live() is False

    def test_a_real_bar_promotes(self):
        assert _teach(AttentionGate()).tuning_live() is True

    def test_the_report_follows_the_live_gate(self):
        import inspect
        from dreamlayer.ai_brain.server import server as s
        src = inspect.getsource(s)
        assert "DL_WIRED_PERSONA_TUNING" in src
        assert "tuning_live" in src, (
            "promotion must follow a bar tune() actually returned, not hulearn "
            "being importable")


class TestTheRuleStaysReadable:
    """The argument for human-learn over a model is that the answer is a
    sentence. If the rule stops being one, the capability stops being itself."""

    def test_the_rule_is_four_lines_and_says_what_it_does(self):
        assert _above_confidence([{"confidence": 0.9}], 0.8) == [True]
        assert _above_confidence([{"confidence": 0.7}], 0.8) == [False]

    def test_a_missing_confidence_reads_as_zero_inside_the_rule(self):
        assert _above_confidence([{}], 0.8) == [False]

    def test_the_rule_is_picklable(self):
        # GridSearchCV pickles the estimator for the cross-validated path; a
        # lambda or a closure here would fail only when hulearn is installed,
        # which is the one configuration the fallback tests cannot catch.
        import pickle
        assert pickle.loads(pickle.dumps(_above_confidence)) is _above_confidence


class TestItIsReachableOverHTTP:
    """Registered in a route table is not reachable. This drives the real
    server the way the Live Lens does — the only thing that proves the label
    can actually cross back from the glass."""

    def _live(self, tmp_path):
        from dreamlayer.tests.test_brain_capabilities import _Live
        return _Live(tmp_path)

    def test_a_swat_posted_over_http_becomes_a_label(self, tmp_path):
        from dreamlayer.tests.test_brain_capabilities import _req
        live = self._live(tmp_path)
        try:
            code, body = _req(live.url + "/dreamlayer/attention",
                              {"kind": "candor", "confidence": 0.42,
                               "dismissed": True}, live.h)
            assert code == 200, body
            assert body["ok"] is True and body["labelled"] == 1
            assert body["swatted"] == 1
            code, body = _req(live.url + "/dreamlayer/attention",
                              {"kind": "candor", "confidence": 0.91,
                               "dismissed": False}, live.h)
            assert body["labelled"] == 2 and body["swatted"] == 1, body
        finally:
            live.stop()

    def test_a_card_with_no_confidence_posts_but_does_not_label(self, tmp_path):
        from dreamlayer.tests.test_brain_capabilities import _req
        live = self._live(tmp_path)
        try:
            code, body = _req(live.url + "/dreamlayer/attention",
                              {"kind": "candor", "dismissed": True}, live.h)
            assert code == 200 and body["ok"] is True
            assert body["labelled"] == 0, (
                "a card with no confidence became a label; the gate would be "
                "fitting a bar on a number nobody was shown")
        finally:
            live.stop()

    def test_the_route_needs_the_token(self, tmp_path):
        from dreamlayer.tests.test_brain_capabilities import _req
        live = self._live(tmp_path)
        try:
            code, _ = _req(live.url + "/dreamlayer/attention",
                           {"kind": "candor", "confidence": 0.5,
                            "dismissed": True}, None)
            assert code in (401, 403), code
        finally:
            live.stop()

    def test_the_label_survives_a_brain_restart(self, tmp_path):
        from dreamlayer.ai_brain.server.attention_live import gate
        from dreamlayer.ai_brain.server.server import Brain
        from dreamlayer.tests.test_brain_capabilities import _req
        live = self._live(tmp_path)
        n = MIN_LABELLED + 4
        try:
            for i in range(n):
                conf = round(0.55 + (i % 8) * 0.05, 2)
                _req(live.url + "/dreamlayer/attention",
                     {"kind": "candor", "confidence": conf,
                      "dismissed": conf < 0.80}, live.h)
        finally:
            live.stop()
        again = Brain(live.cfg_dir)
        assert gate(again).summary()["labelled"] == n, (
            "the wearer\'s swats did not reach disk, so every restart would "
            "throw the bar away and the gate could never settle")
