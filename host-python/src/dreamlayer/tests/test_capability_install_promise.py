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


class TestSomeOfThemDoRunJustNotHere:
    """`_NOT_WIRED` is a statement about the BRAIN, which is the machine running
    the capabilities page. For two entries that makes "dormant" correct and the
    REASON wrong — they are wired on the glasses hub, and a wearer told "nothing
    calls this" would conclude a feature they use every day does not exist."""

    def test_the_hub_set_is_not_empty_and_is_inside_not_wired(self):
        assert cap._RUNS_ON_HUB
        assert set(cap._RUNS_ON_HUB) <= cap._NOT_WIRED

    @pytest.mark.parametrize("key,site", sorted(cap._RUNS_ON_HUB.items()))
    def test_each_names_a_constructor_that_is_still_there(self, key, site):
        """The claim is checkable rather than remembered: if the hub stops
        building it, this fails and the entry has to move."""
        c = cap._BY_KEY.get(key)
        if c is None:
            pytest.skip(f"{key} is no longer declared")
        src = (pathlib.Path(cap.__file__).parent / site).read_text(encoding="utf-8")
        seam = pathlib.Path(cap.__file__).parent / c.seam
        import ast as _ast
        names = {n.name for n in _ast.parse(seam.read_text(encoding="utf-8")).body
                 if isinstance(n, (_ast.ClassDef, _ast.FunctionDef))
                 and not n.name.startswith("_")}
        assert any(f"{n}(" in src for n in names), (
            f"{site} no longer constructs anything from {c.seam}")

    def test_runs_on_partitions_cleanly(self):
        for c in cap.CAPABILITIES:
            where = cap.runs_on(c)
            assert where in ("brain", "hub", ""), (c.key, where)
            if where == "hub":
                assert c.key in cap._RUNS_ON_HUB
            if where == "":
                assert c.key in cap._NOT_WIRED

    def test_both_surfaces_say_where_rather_than_denying_it(self):
        panel = (pathlib.Path(cap.__file__).parent / "ai_brain" / "server"
                 / "panel.py").read_text(encoding="utf-8")
        body = panel.split('if(it.state==="missing"){', 1)[1][:2200]
        assert 'it.runs_on==="hub"' in body
        assert "runs on your glasses, not here" in body
        # …and the hub branch is checked FIRST, or a hub capability would be
        # labelled inert by the branch above it
        assert body.index('it.runs_on==="hub"') < body.index("wires_on_install===false")

        root = pathlib.Path(cap.__file__).parents[3] / "phone-app"
        screen = root / "app" / "capabilities.tsx"
        if not screen.exists():
            pytest.skip("phone-app not in this checkout")
        text = screen.read_text(encoding="utf-8")
        assert 'runs_on === "hub"' in text
        assert "These run on your glasses" in text
        # a hub capability must not also appear under "nothing calls them yet"
        assert 'runs_on !== "hub"' in text


class TestAPackDoesNotSellAnInertCapability:
    """A pack is the ONE-CLICK unit — on a frozen build the panel says "add with
    a pack ↓" and the tagline is the whole pitch. Three of them named a specific
    capability that installing could not switch on:

      * Total Recall promised "deduped", which is `memory_dedup` — and that runs
        on the GLASSES, so a Mac install of this pack does not switch it on.
      * Clear Eyes promised "identity-stable tracking", which is
        `object_tracking` — nothing in the tree feeds it frames.
      * Guardian promised "structured cancellation", which is
        `structured_concurrency` — Orchestrator-only.

    The Operator pack was already written the honest way and is the model: name
    what works "today", then say the rest ships "as libraries" for surfaces
    still being wired.
    """

    @staticmethod
    def _inert(pack):
        return [c for c in pack.caps() if not cap.wires_on_install(c)]

    def test_the_check_has_something_to_check(self):
        packs = [p for p in cap.PACKS if self._inert(p)]
        assert packs, "no pack carries an inert capability — update this file"

    @pytest.mark.parametrize("key,phrase", [
        ("recall", "deduped"),
        ("eyes", "identity-stable tracking,"),
        ("guardian", "structured cancellation."),
    ])
    def test_the_bare_promise_is_gone(self, key, phrase):
        """Each phrase named an inert capability as a flat selling point."""
        p = next(x for x in cap.PACKS if x.key == key)
        assert phrase not in p.tagline, (
            f"{key} sells {phrase!r} again — that capability cannot be switched "
            "on by installing this pack")

    @pytest.mark.parametrize("key", ["recall", "eyes", "guardian", "operator"])
    def test_a_pack_carrying_inert_caps_says_so(self, key):
        """Not a blanket rule — only packs that actually carry one. A pack whose
        every capability wires on install should NOT be hedged, or the hedge
        stops meaning anything."""
        p = next(x for x in cap.PACKS if x.key == key)
        assert self._inert(p), f"{key} no longer carries an inert cap"
        low = p.tagline.lower()
        assert ("librar" in low or "does not" in low), (
            f"{key} carries {len(self._inert(p))} capabilities that installing "
            "cannot switch on and its tagline does not say so")

    def test_a_fully_live_pack_is_not_hedged(self):
        """The other side of the same rule, so the hedge stays informative."""
        for p in cap.PACKS:
            if self._inert(p):
                continue
            assert "as those surfaces come online" not in p.tagline, p.key

    def test_the_hub_one_says_it_is_the_glasses_not_a_someday(self):
        """`memory_dedup` is not unfinished — it runs. Saying "coming soon"
        about a feature the wearer's glasses use would be the wrong hedge."""
        p = next(x for x in cap.PACKS if x.key == "recall")
        assert "GLASSES" in p.tagline or "glasses" in p.tagline
