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
        assert SINKS, "empty registry — this loop would check nothing"
        for s in SINKS.values():
            if s.switch is not None:
                assert hasattr(brain.config, s.switch), (
                    f"{s.key} names a switch that is not on BrainConfig: "
                    f"{s.switch}")

    def test_a_sink_has_a_switch_or_a_predicate_or_needs_a_grant(self):
        assert SINKS, "empty registry — this loop would check nothing"
        for s in SINKS.values():
            assert not (s.switch and s.predicate), (
                f"{s.key} has two sources of truth for one decision")

    def test_the_scopes_are_the_declared_ones(self):
        from dreamlayer.ai_brain.server.consent_gate import LAN, RADIO
        assert SINKS, "empty registry — this loop would check nothing"
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

    def test_the_lexicon_lookup_asks_the_gate(self, brain, monkeypatch):
        """Asserted by BEHAVIOUR — the connector must not be reached at all.

        The gate reads `lexicon_enabled`, which is the feature's own switch, so
        this is not a second opt-in. What it buys is that the one thing on the
        ear's path that egresses is counted, carries the Veil, and appears on
        `/dreamlayer/status` beside everything else that can reach off-device.
        """
        from dreamlayer.ai_brain.server.lexicon_live import LexiconRead
        reached = []
        lex = LexiconRead(brain)
        lex._define = lambda w: reached.append(w) or {"sense": "a definition"}

        brain.config.lexicon_enabled = False
        assert lex._lookup("obstreperous") == {}
        assert reached == [], "a word left the device without consent"

        brain.config.lexicon_enabled = True
        assert lex._lookup("obstreperous")
        assert reached == ["obstreperous"]
        assert {r["key"]: r for r in consent(brain).report()}["lexicon"]["sent"] == 1

    def test_the_veil_stops_the_lexicon_even_when_enabled(self, brain,
                                                          monkeypatch):
        from dreamlayer.ai_brain.server.lexicon_live import LexiconRead
        reached = []
        brain.config.lexicon_enabled = True
        lex = LexiconRead(brain)
        lex._define = lambda w: reached.append(w) or {"sense": "x"}
        monkeypatch.setattr(type(brain), "incognito_now", lambda self: True)
        assert lex._lookup("obstreperous") == {}
        assert reached == []

    def test_it_is_built_once_and_held(self, brain):
        assert consent(brain) is consent(brain)


#: One OFF reply, in the shape `lookup_by_barcode` parses (status 1 + product).
_OFF_REPLY = ('{"status": 1, "product": {"product_name": "Hazelnut spread", '
              '"nutriscore_grade": "e"}}')


class TestTheKeylessConnectorsAreOnTheList:
    """#611 — a partial registry reads as a complete one.

    `/dreamlayer/status` could say "your device has talked to a cloud provider
    and to a dictionary" while a barcode glance had been querying Open Food
    Facts all afternoon, and `anything_left()` answered False. These are the two
    keyless connectors the SHIPPED Brain reaches; `decisions/0010` and
    `decisions/0011` record why the other six in that issue are not here.
    """

    def test_registering_them_did_not_switch_them_off(self, brain):
        """The gate fails CLOSED, so a sink with no switch and no predicate
        would have silently killed a lookup that has always been on. That is the
        one way this change could have cost the wearer something."""
        g = EgressConsent(brain)
        rows = {r["key"]: r for r in g.report()}
        for key in ("openfoodfacts", "plugin_registry"):
            assert g.allowed(key) is True, f"{key} was registered default-DENY"
            assert rows[key]["needs_grant"] is False, key

    def test_the_veil_is_what_they_are_consented_on(self, brain, monkeypatch):
        """Asserted against `_predicate` directly, because `allowed()` asks the
        Veil before it ever reaches the predicate — so a predicate that answered
        "yes, always" would be a bare grant wearing a predicate's name, and
        nothing driving `allowed()` could tell the difference."""
        g = EgressConsent(brain)
        for key in ("openfoodfacts", "plugin_registry"):
            sink = SINKS[key]
            assert sink.switch is None and sink.predicate == "veil_is_down", key
            assert g._predicate(sink) is True, key
            monkeypatch.setattr(type(brain), "incognito_now", lambda self: True)
            assert g._predicate(sink) is False, key
            monkeypatch.undo()

    def test_a_barcode_glance_counts_as_something_leaving(self, brain):
        """The headline complaint: a glance had left the device and
        `anything_left()` still answered False."""
        g = consent(brain)
        assert g.anything_left() is False
        g.note("openfoodfacts")
        assert g.anything_left() is True

    # -- the call sites ------------------------------------------------------

    def test_the_barcode_lookup_asks_the_gate(self, brain):
        """Asserted by BEHAVIOUR — the connector must not be REACHED at all, not
        merely return nothing. A stub can fake a return value."""
        from dreamlayer.ai_brain.server.world_lens import barcode_lookup_fn
        fetched: list = []
        lookup = barcode_lookup_fn(
            brain, fetch_fn=lambda url: fetched.append(url) or _OFF_REPLY)

        brain.config.network_mode = "lan_only"       # the Veil, up
        assert lookup("3017620422003") == {}
        assert fetched == [], "a barcode left the device while veiled"

        brain.config.network_mode = "connected"
        assert lookup("3017620422003")["product_name"] == "Hazelnut spread"
        assert len(fetched) == 1
        assert {r["key"]: r
                for r in consent(brain).report()}["openfoodfacts"]["sent"] == 1

    def test_a_second_glance_at_the_same_jar_is_not_a_second_send(self, brain):
        """`note` sits on the FETCH, inside the connector's TTL cache, so the
        ledger counts what actually left rather than how often a lens asked."""
        from dreamlayer.ai_brain.server.world_lens import barcode_lookup_fn
        fetched: list = []
        lookup = barcode_lookup_fn(
            brain, fetch_fn=lambda url: fetched.append(url) or _OFF_REPLY)
        assert lookup("3017620422003") and lookup("3017620422003")
        assert len(fetched) == 1, "the cache was bypassed — retune this test"
        assert {r["key"]: r
                for r in consent(brain).report()}["openfoodfacts"]["sent"] == 1

    def test_the_lens_the_brain_actually_builds_is_the_gated_one(self, brain,
                                                                 monkeypatch):
        """The two above drive `barcode_lookup_fn` directly, which says nothing
        about whether the SHIPPED lens is wired to it — restoring the old
        ungated `off_barcode_fn(...)` at the registration in `WorldLensHost`
        leaves both of them green. So this one asks the Brain for its own world
        lens and puts a barcode through the provider it registered."""
        from dreamlayer.object_lens.schema import ObjectSighting
        from dreamlayer.plugins import openfoodfacts
        # patched BEFORE `world_lens()`: the fetch is bound when the lens is
        # built, so a later patch would rebind nothing.
        monkeypatch.setattr(openfoodfacts, "_default_fetch",
                            lambda url, **kw: _OFF_REPLY)

        wl = brain.world_lens()
        barcode = next(p for p in wl.object_lens.registry._providers
                       if p.name == "barcode")
        rows = barcode.build(ObjectSighting(
            label="jar of spread", confidence=0.9,
            attributes={"barcode": "3017620422003"}))

        assert [r.label for r in rows if r.kind == "info"] == ["Hazelnut spread"]
        assert {r["key"]: r
                for r in consent(brain).report()}["openfoodfacts"]["sent"] == 1, (
            "the barcode lens the Brain builds bypassed the consent gate")

    def test_the_plugin_registry_fetch_asks_the_gate(self, brain, monkeypatch):
        """Same shape, same assertion: the pinned registry must not be reached.

        `store_catalogue` already refuses while veiled; this is checked at the
        fetch itself so a future second caller cannot route around it — the
        reason `lexicon_live` gates the lookup rather than the utterance."""
        from dreamlayer.plugins import registry_client
        fetched: list = []
        monkeypatch.setattr(registry_client, "fetch_index",
                            lambda *a, **k: fetched.append(1) or {"plugins": []})

        brain.config.network_mode = "lan_only"       # the Veil, up
        with pytest.raises(PermissionError):
            brain._fetch_registry_index()
        assert fetched == [], "the registry was reached while veiled"

        brain.config.network_mode = "connected"
        assert brain._fetch_registry_index() == {"plugins": []}
        assert fetched == [1]
        assert {r["key"]: r
                for r in consent(brain).report()}["plugin_registry"]["sent"] == 1

    def test_the_store_still_browses_when_the_veil_is_down(self, brain,
                                                            monkeypatch):
        """The privacy contract runs the other way too: registering a sink must
        never become a way to STOP something the wearer already had.

        The `sent` assertion is the other half, and it is here because this is
        the one test that drives the SHIPPED browse: `store_catalogue` calling
        `registry_client.fetch_index()` again instead of the gated
        `_fetch_registry_index()` would still browse, and only the ledger
        notices."""
        from dreamlayer.plugins import registry_client
        monkeypatch.setattr(registry_client, "fetch_index",
                            lambda *a, **k: {"updated": "2026-08-09",
                                             "plugins": []})
        brain.config.network_mode = "connected"
        assert brain.store_catalogue().get("plugins") == []
        assert {r["key"]: r
                for r in consent(brain).report()}["plugin_registry"]["sent"] == 1, (
            "the store browse bypassed the consent gate")
