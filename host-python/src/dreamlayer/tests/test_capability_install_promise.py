"""Installing a capability's extra should switch that capability on.

For most of the catalogue it does — installing IS the wiring. For entries in
`_NOT_WIRED` it depends, and the difference was invisible at both surfaces:

  * the PANEL renders a `missing` capability as `pip install "dreamlayer[X]"`
    with a Copy button;
  * the PHONE lists them under "Your Brain can also learn to", captioned
    "Install the matching profile on your Mac to switch these on".

Twelve capabilities have no live caller and no runtime promotion, so copying
that command bought a download and landed on "installed · not active yet" —
and the phone's caption promised the one thing installing would not do.

Thirteen OTHERS in `_NOT_WIRED` are promoted at runtime (`DL_WIRED_<KEY>`) by a
subsystem that really does drive them — the eight the ear sets while the
microphone is open, plus five with their own live paths. For those, "install the
extra and switch the feature on" is true, and they must keep saying so.

`wires_on_install` is that distinction, carried in the payload so both surfaces
can tell the two apart.
"""
from __future__ import annotations

import pathlib

import pytest

from dreamlayer import capabilities as cap


class TestTheDistinctionIsReal:
    def test_something_is_on_each_side_of_it(self):
        """A partition with an empty side would be a field that means nothing."""
        wires = [c for c in cap.CAPABILITIES if cap.wires_on_install(c)]
        inert = [c for c in cap.CAPABILITIES if not cap.wires_on_install(c)]
        assert len(wires) > 40
        assert len(inert) > 5

    def test_everything_outside_not_wired_installs_into_life(self):
        """Outside `_NOT_WIRED`, installing IS the wiring — that is what the
        set means."""
        for c in cap.CAPABILITIES:
            if c.key not in cap._NOT_WIRED:
                assert cap.wires_on_install(c) is True, c.key

    def test_the_promoted_ones_keep_their_promise(self):
        for key in cap._PROMOTED_AT_RUNTIME:
            c = cap._BY_KEY.get(key)
            if c is None:
                pytest.skip(f"{key} is no longer declared")
            assert cap.wires_on_install(c) is True, key

    def test_a_dormant_adapter_with_no_live_caller_does_not(self):
        for key in ("typed_pipeline", "memory_dedup", "asr_alignment",
                    "persona_tuning", "wake_word"):
            c = cap._BY_KEY.get(key)
            if c is None:
                continue
            assert cap.wires_on_install(c) is False, key


class TestThePromotedSetIsNotAGuess:
    def test_it_matches_the_ear_that_actually_sets_the_flags(self):
        """`EAR_CAPS` is the list `ear.py` iterates when it opens the
        microphone. If the ear stops driving one, this catches the drift rather
        than leaving the panel promising an install would switch it on."""
        from dreamlayer.ai_brain.server.ear import EAR_CAPS
        assert set(EAR_CAPS) <= cap._PROMOTED_AT_RUNTIME

    def test_every_other_promoted_key_has_a_real_DL_WIRED_setter(self):
        """The five non-ear entries each need code that sets their flag —
        otherwise the promise is as empty as the one this file is about."""
        root = pathlib.Path(cap.__file__).parent
        src = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in root.rglob("*.py") if "tests" not in p.parts)
        from dreamlayer.ai_brain.server.ear import EAR_CAPS
        for key in sorted(cap._PROMOTED_AT_RUNTIME - set(EAR_CAPS)):
            assert f"DL_WIRED_{key.upper()}" in src, (
                f"{key} is declared promoted-at-runtime and nothing sets "
                f"DL_WIRED_{key.upper()}")

    def test_no_promoted_key_is_outside_not_wired(self):
        """Promotion only means anything for a cap that would otherwise read
        dormant; listing a live one here would be noise that hides drift."""
        assert cap._PROMOTED_AT_RUNTIME <= cap._NOT_WIRED


class TestBothSurfacesCarryIt:
    def test_the_payload_carries_the_flag(self):
        rows = cap.report()
        assert all("wires_on_install" in r for r in rows)
        flagged = [r["key"] for r in rows
                   if r["state"] == "missing" and not r["wires_on_install"]]
        assert flagged, (
            "no missing capability is flagged — either every dormant adapter "
            "got wired (good, update this) or the flag stopped being computed")

    def test_the_panel_says_installing_will_not_switch_it_on(self):
        src = (pathlib.Path(cap.__file__).parent / "ai_brain" / "server"
               / "panel.py").read_text(encoding="utf-8")
        body = src.split('if(it.state==="missing"){', 1)[1][:1600]
        assert "wires_on_install===false" in body
        assert "won\\u2019t switch it on yet" in body

    def test_the_phone_does_not_promise_the_install_switches_them_on(self):
        root = pathlib.Path(cap.__file__).parents[3] / "phone-app"
        screen = root / "app" / "capabilities.tsx"
        if not screen.exists():
            pytest.skip("phone-app not in this checkout")
        text = screen.read_text(encoding="utf-8")
        # the two groups are drawn separately…
        assert "wires_on_install !== false" in text
        assert "wires_on_install === false" in text
        # …and the "switch these on" caption belongs to the group it is true of
        head, tail = text.split("Built, but nothing calls them yet", 1)
        assert "switch these on" in head
        assert "switch these on" not in tail

    def test_the_type_admits_an_older_brain(self):
        """A Brain that predates the field sends nothing; `!== false` reads that
        as "assume it wires", which is how everything behaved before."""
        root = pathlib.Path(cap.__file__).parents[3] / "phone-app"
        store = root / "src" / "state" / "useCapabilityStore.ts"
        if not store.exists():
            pytest.skip("phone-app not in this checkout")
        assert "wires_on_install?: boolean" in store.read_text(encoding="utf-8")
