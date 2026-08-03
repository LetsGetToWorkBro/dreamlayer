"""test_consent_gate.py — one place that answers "what is this doing, and to whom?"

The product's answer to a hard feature is CONSENT, not refusal: it will run face
recognition, voice recognition and a third-party lookup, and the wearer decides
per thing, knowing what each does. What was missing was somewhere to decide
from — the switches existed in a dozen places with a dozen names, so the
question could only be answered by reading the source.

Two properties carry the whole design and most of what follows is about them:

  * it SURFACES existing consent rather than demanding it again, so a wearer who
    turned the cloud on last month is not silently switched off;
  * it fails CLOSED on anything it does not recognise, because "I do not know
    what this sends or where" has one safe reading.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.consent_gate import (
    INTERNET, ON_DEVICE, SINKS, EgressConsent, consent)
from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


class TestItSurfacesExistingConsentRatherThanDemandingItAgain:
    """Wrapping a working cloud tier in a fresh default-deny would break
    installs that consented long ago — punishing the honest case to make a
    diagram tidier."""

    def test_a_switch_the_wearer_already_flipped_counts(self, brain):
        g = EgressConsent(brain)
        brain.config.cloud_enabled = False
        assert g.allowed("cloud_ask") is False
        brain.config.cloud_enabled = True
        assert g.allowed("cloud_ask") is True

    def test_a_configured_destination_counts_as_consent(self, brain):
        """Nobody types their own Home Assistant address by accident — a
        non-empty destination is a stronger signal than a checkbox."""
        g = EgressConsent(brain)
        assert g.allowed("home_assistant") is False
        brain.config.home_assistant_url = "http://192.168.1.10:8123"
        assert g.allowed("home_assistant") is True

    def test_whitespace_is_not_a_destination(self, brain):
        brain.config.home_assistant_url = "   "
        assert EgressConsent(brain).allowed("home_assistant") is False

    def test_a_local_api_endpoint_is_not_egress_at_all(self, brain):
        """The Brain already draws this line for the answer tier; drawing it
        differently here would make the panel disagree with the behaviour."""
        g = EgressConsent(brain)
        brain.config.api_base_url = "http://127.0.0.1:11434/v1"
        assert g.allowed("api_brain") is False
        brain.config.api_base_url = "https://api.example.com/v1"
        assert g.allowed("api_brain") is True

    @pytest.mark.parametrize("key", ["face_recognition", "face_auto_enrol",
                                     "voice_recognition", "voice_auto_enrol"])
    def test_the_biometric_switches_are_read_not_replaced(self, brain, key):
        g = EgressConsent(brain)
        setattr(brain.config, key, False)
        assert g.allowed(key) is False
        setattr(brain.config, key, True)
        assert g.allowed(key) is True


class TestWhatNeedsItsOwnYes:
    def test_the_radio_needs_an_explicit_grant(self, brain):
        """Plugging a radio in is not consent to TRANSMIT — LoRa is an
        unauthenticated broadcast heard by everyone in range."""
        g = EgressConsent(brain)
        assert g.allowed("mesh") is False
        brain.config.mesh_tcp_host = "192.168.1.30"
        assert g.allowed("mesh") is False, (
            "configuring a node was read as consent to broadcast")
        g.grant("mesh")
        assert g.allowed("mesh") is True

    def test_a_grant_survives_a_restart(self, brain):
        consent(brain).grant("mesh")
        again = Brain(brain.cfg_dir)
        assert consent(again).allowed("mesh") is True

    def test_revoking_takes_effect(self, brain):
        g = consent(brain)
        g.grant("mesh")
        g.revoke("mesh")
        assert g.allowed("mesh") is False

    def test_granting_something_unregistered_is_refused(self, brain):
        assert consent(brain).grant("not-a-sink") is False


class TestItFailsClosed:
    def test_an_unregistered_sink_is_never_allowed(self, brain):
        """A new egress path nobody described. "I do not know what this sends
        or where" has one safe reading."""
        assert EgressConsent(brain).allowed("some_new_thing") is False

    def test_the_veil_outranks_every_grant(self, brain, monkeypatch):
        """A grant given last month is not consent to act during a moment the
        wearer has explicitly closed."""
        g = EgressConsent(brain)
        brain.config.cloud_enabled = True
        assert g.allowed("cloud_ask") is True
        monkeypatch.setattr(type(brain), "incognito_now", lambda self: True)
        assert g.allowed("cloud_ask") is False

    def test_an_unreadable_posture_is_treated_as_veiled(self, brain,
                                                        monkeypatch):
        g = EgressConsent(brain)
        brain.config.cloud_enabled = True

        def _boom(self):
            raise RuntimeError("trust store unreadable")
        monkeypatch.setattr(type(brain), "incognito_now", _boom)
        assert g.allowed("cloud_ask") is False


class TestTheLedgerIsAFactNotASetting:
    def test_allowed_and_sent_are_different_questions(self, brain):
        g = EgressConsent(brain)
        brain.config.cloud_enabled = True
        row = {r["key"]: r for r in g.report()}["cloud_ask"]
        assert row["allowed"] is True and row["sent"] == 0
        g.note("cloud_ask")
        assert {r["key"]: r for r in g.report()}["cloud_ask"]["sent"] == 1

    def test_a_refusal_is_counted_so_a_dead_feature_is_legible(self, brain):
        """A feature that quietly does nothing looks broken. Counting the
        refusal is what lets a surface say "it asked, and you have not said
        yes" instead of showing silence."""
        g = EgressConsent(brain)
        assert g.check("mesh") is False
        assert {r["key"]: r for r in g.report()}["mesh"]["refused"] == 1

    def test_check_counts_only_the_refusals(self, brain):
        g = EgressConsent(brain)
        g.grant("mesh")
        assert g.check("mesh") is True
        assert {r["key"]: r for r in g.report()}["mesh"]["refused"] == 0

    def test_an_on_device_match_is_not_something_leaving(self, brain):
        """Folding the two together would make "has my device talked to
        anything?" useless — a face matched locally is consequential and is not
        egress."""
        g = EgressConsent(brain)
        g.note("face_recognition")
        assert g.anything_left() is False
        g.note("mesh")
        assert g.anything_left() is True


class TestTheReportReadsAsAnAnswer:
    def test_the_furthest_reaching_come_first(self, brain):
        scopes = [r["scope"] for r in EgressConsent(brain).report()]
        assert scopes == sorted(
            scopes, key=lambda s: {INTERNET: 0, "radio": 1, "lan": 2,
                                   ON_DEVICE: 3}[s])
        assert scopes[0] == INTERNET

    def test_every_sink_says_what_and_where_in_words(self, brain):
        """These are rendered verbatim for a person deciding, so a blank or a
        type name is a bug — the whole point is that they can tell."""
        for r in EgressConsent(brain).report():
            assert len(r["what"]) > 15, r
            assert len(r["where"]) > 10, r

    def test_the_on_device_ones_say_they_stay(self, brain):
        for r in EgressConsent(brain).report():
            if r["scope"] == ON_DEVICE:
                assert "nowhere" in r["where"], r

    def test_needs_grant_marks_only_the_ones_without_a_switch(self, brain):
        rows = {r["key"]: r for r in EgressConsent(brain).report()}
        assert rows["mesh"]["needs_grant"] is True
        assert rows["cloud_ask"]["needs_grant"] is False
        assert rows["api_brain"]["needs_grant"] is False


class TestTheRegistryStaysHonest:
    """A gate nobody registers with is a gate that is not doing anything."""

    def test_every_named_switch_is_a_real_config_field(self, brain):
        """A typo here fails OPEN in the worst way — `getattr` returns None,
        the sink reads as never-consented, and the feature silently stops."""
        for s in SINKS.values():
            if s.switch is not None:
                assert hasattr(brain.config, s.switch), (
                    f"{s.key} names a switch that is not on BrainConfig: "
                    f"{s.switch}")

    def test_a_sink_has_a_switch_or_a_predicate_or_needs_a_grant(self):
        for s in SINKS.values():
            assert not (s.switch and s.predicate), (
                f"{s.key} has two sources of truth for one decision")

    def test_the_scopes_are_the_declared_ones(self):
        from dreamlayer.ai_brain.server.consent_gate import LAN, RADIO
        for s in SINKS.values():
            assert s.scope in (ON_DEVICE, LAN, RADIO, INTERNET), s

    def test_the_mesh_send_path_asks_the_gate(self):
        """The one egress path wired so far. Asserted against the SOURCE only
        as a tripwire — its behaviour is covered in `test_mesh_live.py`, and
        what this guards is somebody adding a second send that skips the gate.
        """
        import pathlib

        from dreamlayer.ai_brain.server import mesh_live
        src = pathlib.Path(mesh_live.__file__).read_text(encoding="utf-8")
        assert 'consent(self.brain).check("mesh")' in src

    def test_it_is_built_once_and_held(self, brain):
        assert consent(brain) is consent(brain)
