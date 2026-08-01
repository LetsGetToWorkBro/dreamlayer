"""What may interrupt you — the seven switches that reached nothing.

`setFactCheck`, `setProactiveCards`, `setFocus`, `setCue`, `setWakeSource`,
`setWakeFeedback` and `setProactiveAlerts` have shipped in the phone's Settings
since launch. Every one of them called `set(...)` and `persist(...)` — that is
AsyncStorage — and stopped. Nothing on the Brain, the hub or the glasses ever
read any of them. Seven controls the wearer believed in, changing nothing.

Five of them are now enforced at `Brain.push_event`, which is the ONE funnel
every card goes through, so a new push site cannot be born ungated. The two wake
settings cannot be enforced here at all — the Brain wakes nothing — so they are
persisted and PULLED by the glasses hub, which is the only thing that can act on
them.

The two invariants worth guarding hardest, because getting either backwards
turns a preference into a defect:

  * THE VEIL AND A PREFERENCE ARE NOT THE SAME GATE. The Veil is about the
    record and fails CLOSED; a preference is about attention and fails OPEN. An
    unreadable posture must not leak; an unreadable preference must not silence
    a smoke alarm.
  * A DIRECT RESPONSE IS NOT AN INTERRUPTION. Suppressing the card that answers
    what the wearer just did is answering a question with silence.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server import Brain


def _brain(**cfg):
    b = Brain(pathlib.Path(tempfile.mkdtemp()))
    for k, v in cfg.items():
        setattr(b.config, k, v)
    return b


def _pushes(b, kind, card=None, veil_ok=False):
    """Did a push actually reach a stream? Counts deliveries, not intentions."""
    got = []

    class _Q:
        def put_nowait(self, ev):
            got.append(ev)

    b._event_subs = [_Q()]
    b.push_event(kind, card or {"type": "X"}, veil_ok=veil_ok)
    return got


class TestTheSwitchesAreOffByNobody:
    def test_the_products_existing_behaviour_is_the_default(self):
        """Defaults are ON here, unlike almost everything else in the config,
        and that is deliberate: these are not new capabilities being opted into,
        they are existing behaviour becoming controllable. A default of False
        would silently turn the glasses off for everyone who upgrades."""
        from dreamlayer.ai_brain.server.store import BrainConfig
        c = BrainConfig()
        assert c.proactive_cards is True
        assert c.proactive_alerts is True
        assert c.cue_event is True and c.cue_person is True and c.cue_place is True
        assert c.focus_mode is False
        assert sorted(c.wake_sources) == ["gaze", "raise", "tap", "voice"]
        assert sorted(c.wake_feedback) == ["audio", "haptic", "visual"]

    def test_the_one_that_spends_something_is_opt_in(self):
        """A fact-check on every sentence is a different product from one you
        ask for, and it costs a verifier pass per utterance."""
        from dreamlayer.ai_brain.server.store import BrainConfig
        assert BrainConfig().fact_check_enabled is False

    def test_every_switch_can_be_written_over_the_wire(self):
        b = _brain()
        b.apply_config({"proactive_cards": False, "proactive_alerts": False,
                        "focus_mode": True, "cue_event": False,
                        "cue_person": False, "cue_place": False,
                        "fact_check_enabled": True,
                        "wake_sources": ["voice"],
                        "wake_feedback": ["haptic"]})
        assert b.config.proactive_cards is False
        assert b.config.focus_mode is True
        assert b.config.fact_check_enabled is True
        assert b.config.wake_sources == ["voice"]
        assert b.config.wake_feedback == ["haptic"]


class TestProactiveCards:
    @pytest.mark.parametrize("kind", sorted(Brain.PROACTIVE_KINDS))
    def test_every_unasked_card_stops(self, kind):
        b = _brain(proactive_cards=False)
        assert _pushes(b, kind) == []

    @pytest.mark.parametrize("kind", ["ready", "saved_memory", "forget_last",
                                      "consent_required", "stasis",
                                      "quest_reward", "time_scrub"])
    def test_a_direct_response_still_arrives(self, kind):
        """You pinned a memory, froze a thought, asked to rewind. Suppressing
        the card that answers that is answering a question with silence."""
        b = _brain(proactive_cards=False)
        assert len(_pushes(b, kind)) == 1

    def test_on_by_default_they_all_arrive(self):
        b = _brain()
        for kind in Brain.PROACTIVE_KINDS:
            assert len(_pushes(b, kind)) == 1, kind


class TestTheTapOnTheShoulder:
    def test_alerts_off_silences_hark_only(self):
        b = _brain(proactive_alerts=False)
        assert _pushes(b, "hark") == []
        assert len(_pushes(b, "proactive_memory")) == 1

    def test_hark_answers_to_alerts_not_to_a_cue(self):
        """Filing the tap-on-the-shoulder tier under a cue kind would give it
        two masters, so it is deliberately absent from the cue map."""
        assert "hark" not in Brain.CUE_OF_KIND
        b = _brain(cue_event=False, cue_person=False, cue_place=False)
        assert len(_pushes(b, "hark")) == 1

    def test_a_safety_alert_ignores_every_preference(self):
        """`veil_ok` is for a categorical safety alert carrying no captured
        content. That is not a notification anyone opted out of."""
        b = _brain(proactive_cards=False, proactive_alerts=False, focus_mode=True)
        assert len(_pushes(b, "hark", veil_ok=True)) == 1


class TestTheCuePicker:
    @pytest.mark.parametrize("cue,kind", [
        ("event", "brief"), ("event", "commitment_recall"),
        ("event", "commitment_drift"),
        ("person", "proactive_memory"), ("person", "they_said"),
        ("person", "candor"),
        ("place", "object_recall"),
    ])
    def test_turning_one_cue_off_stops_only_its_kinds(self, cue, kind):
        b = _brain(**{f"cue_{cue}": False})
        assert _pushes(b, kind) == []
        # …and the other two cues are untouched
        others = [k for k, c in Brain.CUE_OF_KIND.items() if c != cue]
        for other in others:
            assert len(_pushes(b, other)) == 1, other

    def test_every_cue_kind_names_a_real_cue(self):
        assert set(Brain.CUE_OF_KIND.values()) == {"event", "person", "place"}
        assert set(Brain.CUE_OF_KIND) <= Brain.PROACTIVE_KINDS


class TestFocusIsNotTheVeil:
    def test_focus_hushes_the_live_feeds_too(self):
        """The phone's own words: "cards, captions, and pop-ups hush; capture
        keeps running (unlike incognito)"."""
        b = _brain(focus_mode=True)
        for kind in ("caption", "interpret", "truth", "answer_ahead",
                     "fact_check", "intro", "listening"):
            assert _pushes(b, kind) == [], kind

    def test_focus_leaves_direct_responses_alone(self):
        b = _brain(focus_mode=True)
        for kind in ("ready", "saved_memory", "forget_last", "consent_required"):
            assert len(_pushes(b, kind)) == 1, kind

    def test_focus_does_not_stop_capture(self):
        """The whole difference between this and the Veil, and the assertion
        has to be about the STORE rather than about the shield: focus mode
        raising `incognito_now()` is not the failure mode — dropping the
        utterance on the way in is, and that leaves the shield reading False
        the whole time."""
        from dreamlayer.ai_brain.server.ear import EarHost
        b = _brain(focus_mode=True)
        ear = EarHost(b)
        docs = []
        b.index.add_documents = lambda pairs: docs.extend(pairs)  # type: ignore[assignment]
        ear.ingest_caption("the lease is due on Friday")
        assert ear.heard_count == 1, "focus mode swallowed the utterance"
        assert any("lease" in text for _n, text in docs), \
            "the utterance never reached the store"
        assert b.incognito_now() is False, "focus must not raise the shield"

    def test_focus_hushes_the_caption_of_an_utterance_it_still_keeps(self):
        """Both halves in one assertion: heard and stored, but not drawn."""
        from dreamlayer.ai_brain.server.ear import EarHost
        b = _brain(focus_mode=True, captions_enabled=True)
        drawn = []
        b.push_event = lambda kind, card=None, veil_ok=False: (   # type: ignore[method-assign]
            drawn.append(kind) if Brain._may_interrupt(b, kind) else 0)
        ear = EarHost(b)
        ear.ingest_caption("the lease is due on Friday")
        assert ear.heard_count == 1
        assert "caption" not in drawn


class TestTheTwoGatesAreDistinct:
    def test_the_veil_still_wins_over_an_allowed_kind(self):
        b = _brain()
        b.incognito_now = lambda: True                # type: ignore[method-assign]
        assert _pushes(b, "saved_memory") == []

    def test_a_preference_fails_OPEN_where_the_veil_fails_closed(self):
        """An unreadable posture must not leak; an unreadable PREFERENCE must
        not silence a smoke alarm. Getting these backwards turns a privacy
        control into a reliability bug, or the reverse."""
        b = _brain()

        class _Boom:
            def __getattr__(self, name):
                raise RuntimeError("config unreadable")

        b.config = _Boom()                            # type: ignore[assignment]
        assert b._may_interrupt("hark") is True

        b2 = _brain()
        b2.incognito_now = lambda: (_ for _ in ()).throw(RuntimeError("?"))  # type: ignore[method-assign]
        assert _pushes(b2, "hark") == []

    def test_the_preference_check_runs_after_the_veil_not_instead(self):
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "ai_brain" / "server" / "server.py").read_text(encoding="utf-8")
        body = src.split("def push_event(", 1)[1].split("\n    @staticmethod", 1)[0]
        assert body.index("incognito_now()") < body.index("_may_interrupt(")


class TestTheLiveFactChecker:
    def test_the_ear_checks_when_asked_to(self):
        """The switch has existed on the phone since launch and the Brain grew
        no flag for it, so `LensHost.fact_check` could only ever be reached by
        someone typing a claim into a route."""
        from dreamlayer.ai_brain.server.ear import EarHost
        b = _brain(fact_check_enabled=True)
        seen = []
        ls = b.lenses()
        ls.fact_check = lambda claim, push=True: seen.append(claim)  # type: ignore[assignment]
        EarHost(b).ingest_caption("the tower is four hundred metres tall")
        assert seen == ["the tower is four hundred metres tall"]

    def test_it_stays_quiet_when_not_asked_to(self):
        from dreamlayer.ai_brain.server.ear import EarHost
        b = _brain(fact_check_enabled=False)
        seen = []
        b.lenses().fact_check = lambda claim, push=True: seen.append(claim)  # type: ignore[assignment]
        EarHost(b).ingest_caption("the tower is four hundred metres tall")
        assert seen == []

    def test_it_is_fed_the_scrubbed_text(self):
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "ai_brain" / "server" / "ear.py").read_text(encoding="utf-8")
        body = src.split("def ingest_caption(", 1)[1]
        assert body.index("default_redactor") < body.index("fact_check(text)")

    def test_a_lens_failure_never_breaks_the_ear(self):
        from dreamlayer.ai_brain.server.ear import EarHost
        b = _brain(fact_check_enabled=True)
        b.lenses().fact_check = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))  # type: ignore[assignment]
        EarHost(b).ingest_caption("something said out loud")   # must not raise


class TestTheWakeSettingsReachTheOnlyThingThatCanUseThem:
    def test_the_brain_serves_them(self):
        b = _brain(wake_sources=["voice"], wake_feedback=["haptic"],
                   proactive_cards=False, cue_place=False)
        cfg = b.config
        payload = {
            "wake_sources": list(cfg.wake_sources),
            "wake_feedback": list(cfg.wake_feedback),
        }
        assert payload["wake_sources"] == ["voice"]
        assert payload["wake_feedback"] == ["haptic"]

    def test_the_route_exists_and_carries_both_halves(self):
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "ai_brain" / "server" / "server.py").read_text(encoding="utf-8")
        assert '"/dreamlayer/juno": _get_juno,' in src
        body = src.split("def _get_juno(", 1)[1].split("\n        def ", 1)[0]
        for key in ("wake_sources", "wake_feedback", "interrupts",
                    "proactive_cards", "cue_place", "fact_check"):
            assert key in body, key

    def test_the_hub_pulls_and_applies_them(self):
        from dreamlayer.orchestrator.ops_juno_attention import JunoAttentionOps

        class _Hub(JunoAttentionOps):
            def __init__(self):
                self.brain_url = "http://mac:8765"
                self.brain_token = "t"
                self.wake_sources = {"voice", "tap", "gaze", "raise"}
                self.wake_feedback = {"visual": True, "audio": True, "haptic": True}
                self.applied_cues = {}
                self.anticipation_on = True

            def set_cue(self, kind, on=True):
                self.applied_cues[kind] = on

            def set_anticipation(self, on=True):
                self.anticipation_on = on

        h = _Hub()
        out = h.sync_wake_prefs(http_get=lambda url, tok: {
            "wake_sources": ["voice", "tap"],
            "wake_feedback": ["visual"],
            "interrupts": {"proactive_cards": False, "cue_place": False},
        })
        assert h.wake_sources == {"voice", "tap"}
        assert h.wake_feedback == {"visual": True, "audio": False, "haptic": False}
        assert h.anticipation_on is False
        assert h.applied_cues["place"] is False
        assert out and out["wake_sources"] == ["tap", "voice"]

    def test_an_empty_list_is_an_answer_and_a_missing_key_is_not(self):
        """"I turned them all off" must be distinguishable from "an older Brain
        doesn't know about this"."""
        from dreamlayer.orchestrator.ops_juno_attention import JunoAttentionOps

        class _Hub(JunoAttentionOps):
            def __init__(self):
                self.brain_url = "http://mac"
                self.brain_token = ""
                self.wake_sources = {"voice", "tap"}
                self.wake_feedback = {"visual": True, "audio": True, "haptic": True}

        h = _Hub()
        h.sync_wake_prefs(http_get=lambda u, t: {"wake_sources": []})
        assert h.wake_sources == set()
        assert h.wake_feedback == {"visual": True, "audio": True, "haptic": True}

        h2 = _Hub()
        h2.sync_wake_prefs(http_get=lambda u, t: {"wake_feedback": ["audio"]})
        assert h2.wake_sources == {"voice", "tap"}, "a missing key changed a setting"

    def test_an_unreachable_brain_leaves_the_glasses_exactly_as_they_were(self):
        """Falling back to a default here would quietly re-enable a source the
        wearer switched off."""
        from dreamlayer.orchestrator.ops_juno_attention import JunoAttentionOps

        class _Hub(JunoAttentionOps):
            def __init__(self):
                self.brain_url = "http://mac"
                self.brain_token = ""
                self.wake_sources = {"tap"}
                self.wake_feedback = {"visual": False, "audio": True, "haptic": True}

        h = _Hub()
        assert h.sync_wake_prefs(
            http_get=lambda u, t: (_ for _ in ()).throw(OSError("down"))) is None
        assert h.wake_sources == {"tap"}
        assert h.wake_feedback["visual"] is False

    def test_no_brain_at_all_is_not_an_error(self):
        from dreamlayer.orchestrator.ops_juno_attention import JunoAttentionOps

        class _Hub(JunoAttentionOps):
            brain_url = ""

        assert _Hub().sync_wake_prefs() is None
