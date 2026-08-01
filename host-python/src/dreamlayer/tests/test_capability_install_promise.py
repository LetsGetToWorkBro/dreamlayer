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
        # Walk into top-level `if` blocks, not just `tree.body`. Every optional
        # seam in this tree defines its type under `if _HAS_X:` with an
        # equivalent dataclass in the `else` — so a body-only scan finds nothing
        # in exactly the modules this set is about (`models_pydantic` was the
        # one that caught it).
        def _public(node, out):
            for n in getattr(node, "body", []):
                if isinstance(n, (_ast.ClassDef, _ast.FunctionDef)):
                    if not n.name.startswith("_"):
                        out.add(n.name)
                elif isinstance(n, _ast.If):
                    _public(n, out)
                    for sub in n.orelse:
                        _public(_ast.Module(body=[sub], type_ignores=[]), out)
            return out

        names = _public(_ast.parse(seam.read_text(encoding="utf-8")), set())
        assert names, f"no public names parsed out of {c.seam}"
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


class TestTheMeterOnlyRisesWhenSomethingStartsWorking:
    """The awakening meter is a fraction, and the denominator used to move.

    `power_stats` excluded a capability on its current STATE — `dormant` was
    skipped — so the total shrank the moment something was installed. Installing
    a capability that delivers nothing therefore raised the percent: measured at
    7% → 9% across all 26 inert entries, with the numerator unchanged at 11. The
    wearer downloads libraries, switches on nothing, and the meter congratulates
    them.

    It cut the other way too. An ear capability installed with Listening OFF
    reads `dormant` and left the denominator, so switching the microphone on
    moved both halves of the fraction at once — a jump bigger than the thing
    that caused it.

    The exclusion is now a property of the CAPABILITY: anything that can never
    reach "active" is out of the meter entirely, and everything that can stays
    in whether it is currently on or not.
    """

    @staticmethod
    def _with_installed(keys):
        real = cap.installed
        cap.installed = lambda c: True if c.key in keys else real(c)  # type: ignore[assignment]
        try:
            return cap.power_stats()
        finally:
            cap.installed = real                                      # type: ignore[assignment]

    def test_installing_an_inert_capability_moves_nothing(self):
        inert = {c.key for c in cap.CAPABILITIES if not cap.wires_on_install(c)}
        assert inert, "nothing is inert — update this test"
        before = cap.power_stats()
        after = self._with_installed(inert)
        assert after["power_total"] == before["power_total"], (
            "the denominator moved when a capability that delivers nothing was "
            "installed")
        assert after["power"] == before["power"]
        assert after["percent"] == before["percent"]

    def test_no_inert_capability_is_in_the_denominator_at_all(self):
        """Not merely 'it does not move' — it must not be counted, or a wearer
        could never reach 100% on a machine where those libraries are absent."""
        counted = 0
        for c in cap.CAPABILITIES:
            if c.kind not in ("python", "darwin") or not cap.supported(c):
                continue
            if not cap.wires_on_install(c):
                counted += 1
        stats = cap.power_stats()
        assert stats["total"] + counted >= stats["total"]
        # the meter's own total must exclude every one of them
        live = [c for c in cap.CAPABILITIES
                if c.kind in ("python", "darwin") and cap.supported(c)
                and cap.wires_on_install(c)]
        assert stats["total"] == len(live)

    def test_the_denominator_does_not_move_when_a_runtime_flag_flips(self):
        """The mirrored half: promoting an ear capability must change the
        numerator only."""
        env = {"DL_WIRED_VOICE_VAD": "1", "DL_WIRED_LOCAL_ASR": "1"}
        off = cap.power_stats()
        on = cap.power_stats(env)
        assert on["power_total"] == off["power_total"]
        assert on["power"] >= off["power"]

    def test_a_promoted_capability_is_still_counted_while_it_is_off(self):
        """It CAN reach active — turn Listening on — so it belongs in the
        denominator whether or not the microphone is open right now."""
        from dreamlayer.ai_brain.server.ear import EAR_CAPS
        for key in EAR_CAPS:
            c = cap._BY_KEY.get(key)
            if c is None or c.kind not in ("python", "darwin"):
                continue
            assert cap.wires_on_install(c) is True, key

    def test_full_still_means_every_power_on(self):
        """`fully` drives "fully awakened" copy. Shrinking the denominator was
        also a way to reach it without switching anything on."""
        stats = cap.power_stats()
        assert stats["fully"] == (stats["power_total"] > 0
                                  and stats["power"] >= stats["power_total"])


class TestTheCLISaysItToo:
    """`python -m dreamlayer.capabilities` prints a column headed "switch on
    with" — the promise in its most explicit form anywhere in the product. A
    bare pip command under that header, for a capability nothing calls, is
    simply false: the install succeeds and the row moves "missing" → "dormant".
    """

    def test_a_live_capability_gets_a_clean_command(self):
        """The hedge must not spread to rows where the command is the truth."""
        for key in ("vector_search", "voice_vad", "dashboard"):
            c = cap._BY_KEY.get(key)
            if c is None or c.kind == "service":
                continue
            hint = cap._hint(c)
            assert hint.startswith("pip install")
            assert "nothing calls it" not in hint, key

    def test_an_inert_one_says_the_install_will_not_call_it(self):
        for key in ("typed_docs", "typed_pipeline", "persona_tuning"):
            c = cap._BY_KEY.get(key)
            if c is None:
                continue
            hint = cap._hint(c)
            assert "nothing calls it yet" in hint, key
            # …and still carries the command, because extras are SHARED and the
            # same wheel may switch on a different capability that does run
            assert "pip install" in hint or "manual install" in hint, key

    def test_a_hub_one_says_where_instead_of_offering_a_command(self):
        """Nothing typed on THIS machine switches these on, and nothing is
        broken either — a pip command would be the wrong answer twice."""
        for key in cap._RUNS_ON_HUB:
            c = cap._BY_KEY.get(key)
            if c is None:
                continue
            hint = cap._hint(c)
            assert hint == "runs on your glasses, not here", key
            assert "pip install" not in hint, key

    def test_a_service_still_reports_its_own_note(self):
        """Services are configured, not installed — the earlier branch owns
        them and must keep doing so."""
        svc = [c for c in cap.CAPABILITIES if c.kind == "service"]
        assert svc, "no service capabilities — update this test"
        for c in svc:
            assert cap._hint(c) == c.note, c.key


class TestTypedModelsIsLiveOnTheHubAndInertHere:
    """The claim behind `typed_models` sitting in `_RUNS_ON_HUB`, asserted from
    both ends rather than from a file name.

    Unlike the other two hub entries, its seam is constructed in SHARED code —
    `MemoryDB._veil_check` — so pointing at an orchestrator file would have been
    false. What makes it hub-only is who ATTACHES THE GATE: without one,
    `_veil_check` returns before constructing anything.
    """

    def test_the_invariant_really_does_refuse_a_veiled_write(self):
        import pathlib as _p
        import tempfile
        from dreamlayer.memory.db import MemoryDB
        from dreamlayer.memory.models_pydantic import PrivacyViolation

        class _Shut:
            def allow_capture(self):
                return False

        db = MemoryDB(str(_p.Path(tempfile.mkdtemp()) / "m.db"))
        db.set_privacy(_Shut())
        with pytest.raises(PrivacyViolation):
            db.add_memory("Note", "a secret")

    def test_without_a_gate_the_type_is_never_constructed(self):
        """Which is exactly the Brain's situation, and why it reads dormant."""
        import pathlib as _p
        import tempfile
        from dreamlayer.memory.db import MemoryDB
        db = MemoryDB(str(_p.Path(tempfile.mkdtemp()) / "m.db"))
        assert db._privacy is None
        assert db.add_memory("Note", "written freely") > 0

    def test_the_orchestrator_attaches_one_and_the_brain_does_not(self):
        root = pathlib.Path(cap.__file__).parent
        hub = (root / "orchestrator" / "orchestrator.py").read_text(encoding="utf-8")
        assert "set_privacy(self.privacy)" in hub, (
            "the hub stopped arming the veil invariant — typed_models is no "
            "longer live anywhere and must leave _RUNS_ON_HUB")
        brain = [p for p in (root / "ai_brain").rglob("*.py")]
        armed = [str(p) for p in brain
                 if "set_privacy(" in p.read_text(encoding="utf-8", errors="ignore")]
        assert not armed, (
            "the Brain now arms the veil invariant too — typed_models is live "
            f"here and should move out of _RUNS_ON_HUB: {armed}")
