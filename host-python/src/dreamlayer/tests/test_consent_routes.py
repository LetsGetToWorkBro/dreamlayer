"""`/dreamlayer/consent` — the surface the registry never had.

#609 built the consent registry and wired it into `/dreamlayer/status`. Nothing
read it. The panel fetched that exact endpoint and ignored the field, the phone
used it only as a reachability ping, and the rows were recomputed and thrown
away on every poll.

The sharp end was `mesh`. It is the one sink deliberately given NO switch —
plugging a LoRa radio in is not consent to transmit on an unauthenticated
broadcast everyone in range can hear — so it takes an explicit grant. `grant()`
existed, was tested, and was reachable only from a Python REPL. So a shipped
feature could not be turned on by the person it belongs to: `check("mesh")`
returned False forever and the refusal counter ticked up with nothing to show
it.

These tests drive the real routes over a real socket, because the defect being
fixed was never "the function is wrong" — it was "no request reaches the
function".
"""
from __future__ import annotations

import pytest

from dreamlayer.ai_brain.server.server import Brain
# The socket harness is IMPORTED, not copied. The first draft pasted `_Live`
# in here, which duplicated its `token="tok"` default into a new file and gave
# CodeQL a fresh py/hardcoded-credentials location to report — the one thing
# CI was failing on. Sharing it is the better answer regardless: two copies of
# a test server drift, and the copy loses whatever the original learns.
from dreamlayer.tests.test_brain_lens_wiring import _Live


@pytest.fixture
def live(tmp_path):
    lb = _Live(tmp_path)
    yield lb
    lb.stop()


class TestTheRadioCanFinallyBeTurnedOn:
    """The whole reason this route exists."""

    def test_mesh_starts_refused(self, live):
        from dreamlayer.ai_brain.server.consent_gate import consent
        assert consent(live.brain).allowed("mesh") is False

    def test_a_grant_over_http_takes_effect(self, live):
        from dreamlayer.ai_brain.server.consent_gate import consent
        code, body = live.post("/dreamlayer/consent",
                               {"key": "mesh", "granted": True})
        assert code == 200 and body["ok"] is True
        assert body["allowed"] is True
        assert consent(live.brain).allowed("mesh") is True, (
            "the route answered yes and the gate still refuses")

    def test_revoking_over_http_takes_effect(self, live):
        from dreamlayer.ai_brain.server.consent_gate import consent
        live.post("/dreamlayer/consent", {"key": "mesh", "granted": True})
        code, body = live.post("/dreamlayer/consent",
                               {"key": "mesh", "granted": False})
        assert code == 200 and body["allowed"] is False
        assert consent(live.brain).allowed("mesh") is False

    def test_a_grant_survives_a_restart(self, live, tmp_path):
        """A consent you have to give again every boot is not consent, it is a
        nag. `grant()` writes through `brain.save()`, and this is what proves
        the route reached that rather than only the in-memory set."""
        live.post("/dreamlayer/consent", {"key": "mesh", "granted": True})
        from dreamlayer.ai_brain.server.consent_gate import consent
        again = Brain(tmp_path / "cfg")
        assert consent(again).allowed("mesh") is True


class TestItRefusesRatherThanPretending:
    def test_an_unknown_sink_is_a_400_not_a_quiet_yes(self, live):
        """The gate fails closed on anything it does not recognise, so a typo
        accepted here would be a grant the surface reports and the gate can
        never honour — the panel and the behaviour disagreeing, silently."""
        code, _ = live.post("/dreamlayer/consent",
                            {"key": "messh", "granted": True})
        assert code == 400

    @pytest.mark.parametrize("key", ["cloud_ask", "lexicon", "home_assistant",
                                     "face_recognition", "api_brain"])
    def test_a_switch_backed_sink_is_refused_here(self, live, key):
        """These already have one source of truth — the feature's own toggle,
        or whether the API endpoint is remote. Writing a second one on this
        route is how the two drift apart and the panel starts disagreeing with
        the behaviour. Refused with the switch NAMED, so the caller can go and
        flip the right thing rather than guess."""
        code, _ = live.post("/dreamlayer/consent",
                            {"key": key, "granted": True})
        assert code == 400

    def test_an_empty_body_does_not_grant_anything(self, live):
        code, _ = live.post("/dreamlayer/consent", {})
        assert code == 400


class TestTheReportIsReadable:
    def test_it_lists_every_sink_furthest_reaching_first(self, live):
        code, body = live.get("/dreamlayer/consent")
        assert code == 200 and body["ok"] is True
        rows = body["sinks"]
        assert len(rows) >= 9
        order = {"internet": 0, "radio": 1, "lan": 2, "on_device": 3}
        scopes = [order[r["scope"]] for r in rows]
        assert scopes == sorted(scopes), "a wearer meets the far ones last"

    def test_every_row_says_what_and_where_in_words(self, live):
        """Rendered verbatim to somebody deciding, so a blank or a type name is
        a bug — being able to tell is the entire point."""
        _, body = live.get("/dreamlayer/consent")
        for r in body["sinks"]:
            assert len(r["what"]) > 15, r
            assert len(r["where"]) > 10, r

    def test_nothing_has_left_on_a_fresh_brain(self, live):
        _, body = live.get("/dreamlayer/consent")
        assert body["anything_left"] is False

    def test_an_on_device_match_is_not_something_leaving(self, live):
        """Folding the two together would make "has my device talked to
        anything?" useless. Asserted through the route because that is where a
        surface would read it."""
        from dreamlayer.ai_brain.server.consent_gate import consent
        consent(live.brain).note("face_recognition")
        _, body = live.get("/dreamlayer/consent")
        assert body["anything_left"] is False
        consent(live.brain).note("mesh")
        _, body = live.get("/dreamlayer/consent")
        assert body["anything_left"] is True

    def test_the_report_does_not_build_a_gate_the_brain_was_not_using(self, live):
        """A poll must not be what constructs the thing it reports on — the
        same rule every other status read here follows."""
        assert getattr(live.brain, "_egress_consent", None) is None
        live.get("/dreamlayer/consent")
        assert getattr(live.brain, "_egress_consent", None) is None, (
            "reading the report made the Brain hold a gate it was not using")

    def test_a_grant_however_does_build_one(self, live):
        """The other half — granting is not a read, and the gate it writes
        through has to be the one everything else asks."""
        live.post("/dreamlayer/consent", {"key": "mesh", "granted": True})
        assert getattr(live.brain, "_egress_consent", None) is not None


class TestSomethingActuallyDrawsIt:
    """The defect #610 named was never "the report is wrong" — it was that the
    rows were computed on every poll and drawn by nothing. So these assert a
    SURFACE exists, which is the only thing that was missing."""

    @staticmethod
    def _panel() -> str:
        import pathlib

        from dreamlayer.ai_brain.server import panel as P
        return pathlib.Path(P.__file__).read_text(encoding="utf-8")

    def test_the_panel_reads_the_route(self):
        src = self._panel()
        assert "async function loadConsent" in src
        assert '/dreamlayer/consent' in src

    def test_it_is_called_at_boot_not_merely_defined(self):
        """A renderer nothing calls is the same defect one layer along.

        Asserted against the BOOT SEQUENCE specifically, not a count of the
        name. The first draft did `src.count("loadConsent()") >= 2` and
        SURVIVED deleting the boot call — the definition line
        `async function loadConsent(){` contains `loadConsent()` as a
        substring, and `setConsent` calls it to refresh itself. Two hits, no
        boot, green test: a check answering a narrower question than it looked
        like, which is the whole bug this file is about.
        """
        src = self._panel()
        lines = src.splitlines()
        boot = [n for n, ln in enumerate(lines)
                if "loadCaps()" in ln and "loadReceipt()" in ln]
        assert boot, "the panel boot sequence moved — re-anchor this test"
        window = "\n".join(lines[boot[0]:boot[0] + 4])
        assert "loadConsent()" in window, (
            "loadConsent is defined but the panel never calls it at load, so "
            "the section renders empty — the exact defect #610 reported")

    def test_it_renders_what_and_where_rather_than_rewording_them(self):
        """These strings are written for a person deciding and are asserted as
        real sentences server-side. Re-writing them in the UI would put the
        panel and the gate's own account of itself out of step."""
        src = self._panel()
        i = src.index("async function loadConsent")
        body = src[i:i + 2600]
        assert "it.what" in body and "it.where" in body

    def test_it_shows_a_refusal_rather_than_silence(self):
        """A feature that quietly does nothing looks broken. "It asked, and you
        have not said yes" is a different sentence, and the counter exists to
        let a surface say it."""
        src = self._panel()
        i = src.index("async function loadConsent")
        assert "it.refused" in src[i:i + 2600]

    def test_only_the_grant_sinks_get_a_control(self):
        """The rest already have one source of truth — the feature's own
        toggle. A second control here is how the two drift apart and the panel
        starts disagreeing with the behaviour, which is what the route's 400
        refuses for the same reason."""
        src = self._panel()
        assert "it.needs_grant" in src
        assert "async function setConsent" in src

    def test_it_builds_nodes_rather_than_an_html_string(self):
        """CodeQL flagged the first draft high-severity, and it was right.

        `esc()` in this panel is a correct escaper, but CodeQL cannot see it as
        a sanitizer, so any `innerHTML = <string built from a response>` reads
        as js/xss. More to the point the objection is sound: that pattern is
        safe only while every future edit remembers to wrap every field, and
        `textContent` cannot be got wrong.

        Asserted over the consent renderer only. The rest of the panel still
        uses the string-building pattern and changing all of it is a separate
        job — but nothing NEW should arrive that way.
        """
        src = self._panel()
        i = src.index("async function loadConsent")
        j = src.index("/* --- packs:", i)
        block = src[i:j]
        assert "innerHTML" not in block, (
            "the consent rows are built by string again — use mkEl/textContent")
        assert "textContent" in block and "mkEl(" in block

    def test_the_control_binds_a_listener_not_an_inline_handler(self):
        """An `onclick="setConsent('...')"` attribute puts a response value
        inside executable markup, which is the same taint path one layer along
        and cannot be fixed by escaping alone."""
        src = self._panel()
        i = src.index("function consentControl")
        block = src[i:i + 900]
        assert "addEventListener" in block
        assert "onclick" not in block
