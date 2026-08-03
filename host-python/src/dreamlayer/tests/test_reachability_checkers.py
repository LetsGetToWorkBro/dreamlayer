"""test_reachability_checkers.py — the checkers cannot go vacuous.

Three scripts measure whether the shipped Brain can reach what the product
declares: `lens_reachability.py` (lenses), `hud_reachability.py` (HUD cards) and
`capability_reachability.py` (capabilities). The lens one has its own tests in
`test_brain_lens_hosts.py`; the other two are covered here.

`hud_reachability.py` answers, for every HUD card the product declares, two
questions the Brain side cannot see on its own: does anything a shipped Brain
can reach PRODUCE it, and does `halo-lua` have a real drawing for it.
`capability_reachability.py` asks whether each capability's declared `seam` —
the adapter file that consumes it — is in the Brain's import closure at all.

A checker like this fails in one direction — it stops finding things and reads
as a clean bill of health. Both of the card checker's first two drafts did
exactly that, and both are pinned below:

  * The producer scan counted `hud/cards.py` itself, whose `ALL_SAMPLES` is a
    dict of literal calls to every builder in the file. Result: 0 cards without
    a producer, on a product where 18 of 24 have none.
  * The glass scan matched only quoted card names, and `renderer.lua` dispatches
    through a table with BARE identifier keys (`CommitmentDriftCard =
    function…`). Result: seven cards reported undrawable that have had
    dedicated drawing functions all along. A checker that cries wolf on a third
    of the catalogue gets ignored, which is worse than not having one.

So these tests assert the checker still SEES things, not merely that it runs.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import textwrap

import pytest

SCRIPT = (pathlib.Path(__file__).resolve().parents[4]
          / "scripts" / "hud_reachability.py")


@pytest.fixture(scope="module")
def hud():
    if not SCRIPT.exists():
        pytest.skip("checker not on disk")
    spec = importlib.util.spec_from_file_location("_hud_reachability", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestItReadsWhatTheProductDeclares:

    def test_it_finds_every_declared_hud_feature(self, hud):
        feats = hud._declared_features()
        assert len(feats) >= 20, f"only {len(feats)} features parsed"
        titles = {t for _, t, _ in feats}
        assert "Privacy Veil" in titles

    def test_every_feature_maps_to_a_real_builder(self, hud):
        samples = hud._sample_builders()
        missing = [k for _, _, k in hud._declared_features() if k not in samples]
        assert not missing, f"catalog names cards ALL_SAMPLES does not build: {missing}"

    def test_every_builder_declares_a_card_type(self, hud):
        """The `type` string is the whole contract with the glass — the Lua
        renderer branches on it and nothing else."""
        types = hud._card_types()
        samples = hud._sample_builders()
        for _, title, key in hud._declared_features():
            fn = samples[key]
            assert types.get(fn), f"{title}: {fn}() declares no card type"


class TestTheGlassScanSeesTheDispatchTable:

    def test_it_finds_types_named_as_bare_table_keys(self, hud):
        """`renderer.lua`'s DRAW table is `CommitmentDriftCard = function…`.
        Matching only quoted names missed every card dispatched that way."""
        drawn = hud._drawn_on_glass()
        if not drawn:
            pytest.skip("halo-lua not in this checkout")
        assert "CommitmentDriftCard" in drawn
        assert "TimeScrubNodeCard" in drawn

    def test_it_finds_types_named_in_quoted_comparisons(self, hud):
        drawn = hud._drawn_on_glass()
        if not drawn:
            pytest.skip("halo-lua not in this checkout")
        assert "FactCheckCard" in drawn        # `if card.type == "FactCheckCard"`

    def test_a_name_that_appears_only_in_a_comment_is_not_drawn(self, hud):
        """Comments are stripped first. `renderer.lua` banners each drawing
        function with `-- XCard` and lists names in its header, so leaving them
        in would mark a type as drawn on the strength of a section heading."""
        drawn = hud._drawn_on_glass()
        if not drawn:
            pytest.skip("halo-lua not in this checkout")
        # PaletteShiftCard is deliberately not a drawable card (cards.py says so
        # in as many words) and appears in prose only.
        assert "PaletteShiftCard" not in drawn


class TestTheProducerScanIsNotVacuous:

    def _producers(self, hud):
        lens = hud._lens_module()
        files = lens._sources()
        known = {lens._module_name(p) for p in files}
        _roots, reachable = lens._closure(lens._import_graph(files), known)
        return hud._producers(reachable, set(hud._sample_builders().values()))

    def test_the_defining_module_is_not_counted_as_a_caller(self, hud):
        """The bug that made the first run report a perfect score.
        `hud/cards.py` calls every builder to fill `ALL_SAMPLES`; a module
        calling itself to build its own fixtures is not a caller."""
        made = self._producers(hud)
        for fn, mods in made.items():
            assert f"{hud.PKG}.hud.cards" not in mods, (
                f"{fn}: the card module counted itself as a producer")

    def test_the_demo_is_outside_the_brains_closure_in_the_first_place(self, hud):
        """Why the demo cannot leak in, stated as the mechanism rather than as
        an outcome. `demo/storyboards.py` genuinely calls sixteen card builders,
        so if it were ever reachable it would mark those cards produced — it is
        not reachable, and this is the assertion that would notice if it became
        so."""
        lens = hud._lens_module()
        files = lens._sources()
        known = {lens._module_name(p) for p in files}
        _roots, reachable = lens._closure(lens._import_graph(files), known)
        leaked = [m for m in reachable if m.startswith(f"{hud.PKG}.demo")
                  or m.startswith(f"{hud.PKG}.simulator")]
        assert not leaked, f"the Brain now imports demo/simulator code: {leaked}"

    def test_the_demo_exclusion_holds_even_if_it_became_reachable(self, hud):
        """The belt to that braces, and the reason the exclusion is not dead
        code. Deleting it from `_producers` changes nothing TODAY — mutating it
        away leaves every test green — because the closure already keeps the
        demo out. So this hands `_producers` a reachable set that deliberately
        contains the demo and asserts the explicit exclusion still fires. Both
        halves have to be tested separately or one silently protects the
        other."""
        lens = hud._lens_module()
        files = lens._sources()
        everything = {lens._module_name(p) for p in files}
        assert f"{hud.PKG}.demo.storyboards" in everything, (
            "the fixture module moved; this test no longer proves anything")
        made = hud._producers(everything, set(hud._sample_builders().values()))
        for fn, mods in made.items():
            assert not any(m.startswith(f"{hud.PKG}.demo")
                           or m.startswith(f"{hud.PKG}.simulator")
                           for m in mods), f"{fn}: counted a demo call site"
        # …and with everything reachable, real producers still register.
        assert made.get("hark"), "the exclusion swallowed the real callers too"

    def test_it_still_finds_the_producers_that_do_exist(self, hud):
        """The opposite failure: an exclusion so broad nothing counts. The ear
        genuinely pushes a HarkCard on a smoke alarm, and that has to survive."""
        made = self._producers(hud)
        assert f"{hud.PKG}.ai_brain.server.ear" in made.get("hark", set()), (
            "the ear's real HarkCard producer was excluded")

    def test_the_gap_is_closed_and_the_scan_could_still_see_one(self, hud):
        """THE GAP IS CLOSED: all 24 declared cards now have a Brain-side
        producer. This replaces `test_the_known_gap_is_still_visible`, which
        asserted a real gap existed and instructed its own retirement — "as the
        gap closes this test should fail … read the number, fix the assertion".
        It closed at "Read the room" (`ai_brain/server/truth_live.py`), the last
        one; it had been 15 of 24, then 1.

        Its job survives it. That test proved the scan was not vacuous by
        pointing at a gap that happened to exist, which is a proof with a shelf
        life — the moment the last gap closed, the only evidence that the scan
        could detect one at all disappeared with it. So the non-vacuity is
        demonstrated on a SYNTHETIC gap instead: hide a real producer from the
        reachable set and require the scan to report the card as unproduced.
        That holds no matter how complete the product gets.
        """
        made = self._producers(hud)
        samples = hud._sample_builders()
        gap = [t for _, t, k in hud._declared_features()
               if not made.get(samples[k])]
        assert not gap, f"a declared card lost its Brain-side producer: {gap}"

        # The synthetic gap: take every builder that IS produced, hide the
        # modules that produce it, and require the scan to report it unproduced.
        # Done for all of them rather than one hand-picked builder, because a
        # single choice ages badly — `hark` looked like the ear's alone and is
        # in fact pushed by `server.py` too, so removing only the ear proved
        # nothing. Hiding the full producer set cannot be wrong that way.
        lens = hud._lens_module()
        files = lens._sources()
        known = {lens._module_name(p) for p in files}
        _roots, reachable = lens._closure(lens._import_graph(files), known)
        produced = {fn: mods for fn, mods in made.items() if mods}
        assert produced, "nothing is produced at all; the scan found no call sites"
        for fn, mods in sorted(produced.items()):
            blinded = hud._producers(reachable - mods, {fn})
            assert not blinded[fn], (
                f"{fn}: the scan still reported a producer after every module "
                f"that produces it was excluded — it is not reading call sites")

    def test_the_cards_just_wired_are_out_of_the_gap(self, hud):
        """The other direction: closing a card has to be visible too, or the
        checker is only ever reporting bad news and nobody will believe the
        good. Each of these had a builder and a drawing all along and nothing a
        shipped Brain could reach ever called it."""
        made = self._producers(hud)
        samples = hud._sample_builders()
        closed = {t for _, t, k in hud._declared_features() if made.get(samples[k])}
        for title in ("Where you left it", "Keep a moment", "Ask it anything",
                      "Hey Juno", "Live captions",      # the ear
                      "Always ready", "Privacy Veil",   # the posture pair
                      "Rewind your day",                # the hot ring IS the day
                      "Truth, checked live",            # world-check half
                      "Read the room"):                 # the last one to close
            assert title in closed, f"{title} lost its Brain-side producer"


class TestThePushScanResolvesTheLocalShapes:
    """Issue #578: the push scan's unresolved list was dominated by LOCAL
    shapes a one-hop resolver can name exactly, without inference.

    Each test runs on a SYNTHETIC module written to `tmp_path` and handed to
    the scan through a stub lens — the same idiom as `_stub_lens` further
    down — so the tests pin the resolver's shapes and cannot go stale with
    unrelated product edits. Every assertion is scoped to that synthetic
    module: nothing here claims anything about the real tree, whose
    remaining-unresolved set is pinned separately in
    `TestTheUnresolvedPushCountIsPinned`.
    """

    def _scan(self, hud, tmp_path, monkeypatch, body: str):
        """Run `_pushed_types` over ONE synthetic module, as its only source."""
        p = tmp_path / "synthetic_host.py"
        p.write_text(textwrap.dedent(body), encoding="utf-8")

        class _Lens:
            @staticmethod
            def _sources():
                return [p]

            @staticmethod
            def _module_name(_p):
                return "synthetic.host"

        monkeypatch.setattr(hud, "_lens_module", lambda: _Lens)
        return hud._pushed_types({"synthetic.host"})

    def test_a_constant_keyed_subscript_assignment_resolves(
            self, hud, tmp_path, monkeypatch):
        """The `lens_hosts.py:882` shape: `out["card"] = builder(...)` then
        `self._push(k, out["card"])`. The old `assigns` pass recorded only
        bare-name targets, so this push scanned as unresolvable; a constant
        string key is the same one-hop assignment."""
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            def synthetic_deviation_alert(**kw):
                return {"type": "SyntheticSubscriptCard", "primary": "x"}


            class Host:
                def check(self, push=True):
                    out = {"fired": True}
                    if push:
                        out["card"] = synthetic_deviation_alert(
                            prior_summary="a", new_summary="b")
                        self._push("they_said", out["card"])
                    return out
        """)
        assert pushed.get("SyntheticSubscriptCard") == {"synthetic.host"}, (
            "the synthetic module's subscript-assigned push did not resolve: "
            f"pushed={pushed}")
        assert unresolved == [], (
            "the synthetic module's subscript-assigned push was still counted "
            f"unresolved: {unresolved}")

    def test_a_to_hud_card_with_a_constructed_receiver_resolves(
            self, hud, tmp_path, monkeypatch):
        """The `lens_hosts.py:616` shape with a LOCALLY EXACT receiver:
        `reward = QuestReward()` in the same function makes the receiver's
        class a name lookup, so the class-qualified `to_hud_card` map can
        answer. The decoy class is load-bearing: `to_hud_card` is defined
        nine times in the real tree with a different card type each, and the
        bare-name map must stay void — resolution goes through the receiver.
        """
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            class QuestReward:
                def to_hud_card(self):
                    return {"type": "SyntheticRewardCard", "primary": "x"}


            class Waypoint:
                def to_hud_card(self):
                    return {"type": "SyntheticDecoyCard", "primary": "y"}


            class Host:
                def complete(self, subject):
                    reward = QuestReward()
                    card = reward.to_hud_card()
                    self._push("quest_reward", card)
        """)
        assert pushed.get("SyntheticRewardCard") == {"synthetic.host"}, (
            "the synthetic module's constructed-receiver to_hud_card push did "
            f"not resolve: pushed={pushed}")
        assert "SyntheticDecoyCard" not in pushed, (
            "the synthetic scan confused the two to_hud_card definitions — "
            "it resolved by bare name, not by receiver class")
        assert unresolved == [], (
            "the synthetic module's constructed-receiver to_hud_card push was "
            f"still counted unresolved: {unresolved}")

    def test_a_to_hud_card_with_a_same_file_produced_receiver_resolves(
            self, hud, tmp_path, monkeypatch):
        """The issue's stopping point, applied to the receiver: `reward =
        _make_reward()` where `_make_reward` is defined in the SAME FILE and
        its return is a constructor call. That is still a name lookup, so the
        class-qualified map may answer."""
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            class Reward:
                def to_hud_card(self):
                    return {"type": "SyntheticFactoryCard", "primary": "x"}


            class Decoy:
                def to_hud_card(self):
                    return {"type": "SyntheticDecoyCard", "primary": "y"}


            def _make_reward():
                return Reward()


            class Host:
                def complete(self):
                    reward = _make_reward()
                    card = reward.to_hud_card()
                    self._push("quest_reward", card)
        """)
        assert pushed.get("SyntheticFactoryCard") == {"synthetic.host"}, (
            "the synthetic module's same-file-produced-receiver to_hud_card "
            f"push did not resolve: pushed={pushed}")
        assert "SyntheticDecoyCard" not in pushed, (
            "the synthetic scan confused the two to_hud_card definitions — "
            "it resolved by bare name, not by receiver class")
        assert unresolved == [], (
            "the synthetic module's same-file-produced-receiver to_hud_card "
            f"push was still counted unresolved: {unresolved}")

    def test_a_to_hud_card_with_a_cross_module_receiver_stays_unresolved(
            self, hud, tmp_path, monkeypatch):
        """The other half of the stopping point: `reward = saga.complete(...)`
        is a producing call defined in ANOTHER module (the real :616 shape),
        and following it is real type inference, not a name lookup. The scan
        must report the site unresolved rather than guess — this pins that
        refusal, so it passes on both the old and the new resolver."""
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            class QuestReward:
                def to_hud_card(self):
                    return {"type": "SyntheticRewardCard", "primary": "x"}


            class Decoy:
                def to_hud_card(self):
                    return {"type": "SyntheticDecoyCard", "primary": "y"}


            class Host:
                def complete(self, saga):
                    reward = saga.complete("x")
                    card = reward.to_hud_card()
                    self._push("quest_reward", card)
        """)
        assert not pushed, (
            "the synthetic scan guessed a card type through a cross-module "
            f"receiver: {pushed}")
        assert [u.split(":")[0] for u in unresolved] == ["synthetic.host"], (
            "the synthetic module's cross-module-receiver push was not "
            f"reported unresolved: {unresolved}")

    def test_a_to_hud_card_through_a_factory_with_a_nested_def_stays_unresolved(
            self, hud, tmp_path, monkeypatch):
        """The same refusal, one shape over: `make_thing` never returns a
        Reward — its NESTED helper does. Crediting the helper's return to the
        enclosing factory would invent a receiver class the same-file rule
        never established, and the scan would name a card type that is never
        pushed. The decoy class is load-bearing: it keeps the bare-name
        `to_hud_card` map void, so only the class-qualified path can answer —
        and it must refuse rather than read across the nested `def`."""
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            class Reward:
                def to_hud_card(self):
                    return {"type": "RewardCard", "primary": "x"}

            class Decoy:
                def to_hud_card(self):
                    return {"type": "DecoyCard", "primary": "y"}

            def make_thing():
                def _unused_helper():
                    return Reward()          # nested; make_thing never returns a Reward
                return {"not": "a reward"}

            class Host:
                def go(self):
                    thing = make_thing()
                    self._push("k", thing.to_hud_card())
        """)
        assert not pushed, (
            "the synthetic scan credited a nested helper's return to the "
            f"enclosing factory and invented a pushed card type: {pushed}")
        assert [u.split(":")[0] for u in unresolved] == ["synthetic.host"], (
            "the synthetic module's nested-def-factory push was not reported "
            f"unresolved: {unresolved}")

    def test_an_ifexp_names_every_resolvable_branch(
            self, hud, tmp_path, monkeypatch):
        """The `server.py:1297` shape — the one the issue did not name:
        `card = (cards.private_zone_card(zone) if zone else
        cards.privacy_veil())`. `_pushed_types` is existential — it maps a
        card type to the modules that CAN push it — so each resolvable branch
        is a truthful observation and both must be recorded."""
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            def synthetic_zone_card(zone):
                return {"type": "SyntheticZoneCard", "primary": "x"}


            def synthetic_veil_card():
                return {"type": "SyntheticVeilCard", "primary": "x"}


            class Host:
                def posture(self, zone=None):
                    card = (synthetic_zone_card(zone) if zone
                            else synthetic_veil_card())
                    self._push("private_zone" if zone else "privacy_veil", card)
        """)
        assert pushed.get("SyntheticZoneCard") == {"synthetic.host"}, (
            "the synthetic module's IfExp push lost its True branch: "
            f"pushed={pushed}")
        assert pushed.get("SyntheticVeilCard") == {"synthetic.host"}, (
            "the synthetic module's IfExp push lost its False branch: "
            f"pushed={pushed}")
        assert unresolved == [], (
            "the synthetic module's fully-resolvable IfExp push was still "
            f"counted unresolved: {unresolved}")

    def test_an_ifexp_with_an_opaque_branch_is_reported_and_kept(
            self, hud, tmp_path, monkeypatch):
        """The honest-unknown half of the IfExp rule: a branch that cannot be
        named keeps the site on the unresolved list, but the branch that CAN
        be named is still recorded — naming one branch must neither silence
        the other nor erase it."""
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            def synthetic_zone_card(zone):
                return {"type": "SyntheticZoneCard", "primary": "x"}


            class Host:
                def posture(self, zone=None, fallback=None):
                    card = (synthetic_zone_card(zone) if zone else fallback)
                    self._push("posture", card)
        """)
        assert pushed.get("SyntheticZoneCard") == {"synthetic.host"}, (
            "the synthetic module's half-resolvable IfExp push lost the "
            f"branch it could name: pushed={pushed}")
        assert [u.split(":")[0] for u in unresolved] == ["synthetic.host"], (
            "the synthetic module's half-resolvable IfExp push was not "
            f"reported unresolved: {unresolved}")

    def test_a_push_of_a_function_parameter_stays_unresolved(
            self, hud, tmp_path, monkeypatch):
        """The planted non-vacuity pin the issue demands, mirroring the real
        self-test path (`server.py`: `card = dict(card)` where `card` is a
        function PARAMETER). The card arrives inter-procedurally, so no local
        resolver can name it; the scan must SAY SO rather than invent an
        answer. This pins a preserved property — it passes on the old resolver
        too — and its bite is proven by mutation: a `_resolve` that returns a
        type for everything makes the report more confident and less correct,
        and this is the test that fails when that happens."""
        pushed, unresolved = self._scan(hud, tmp_path, monkeypatch, """
            class Host:
                def selftest(self, card):
                    card = dict(card)
                    card["selftest"] = True
                    self._push("selftest", card)
        """)
        assert [u.split(":")[0] for u in unresolved] == ["synthetic.host"], (
            "the synthetic module's planted parameter-card push was not "
            f"reported unresolved: {unresolved}")
        assert not pushed, (
            "the synthetic scan invented a card type for a push whose card "
            f"is a function parameter: {pushed}")


class TestTheUnresolvedPushCountIsPinned:
    """Issue #578's ratchet: "whatever is left should keep printing, but the
    count should be asserted so it cannot silently grow."

    EXACT equality, deliberately, in both directions. Growth fails — a blind
    spot nobody notices getting bigger is worse than one everybody can see.
    Shrink fails too, and that is the point: when the resolver learns a new
    shape this test SHOULD fail — read the number, verify each remaining
    site genuinely cannot be resolved locally, then move the pin DOWN
    deliberately. The same instruction this file's retired
    `test_the_known_gap_is_still_visible` carried: "as the gap closes this
    test should fail … read the number, fix the assertion".

    Line numbers are stripped from the comparison: they rot with unrelated
    edits — this file's own history proves it — while the count and the
    modules are the substance. This test is scoped to the REAL tree; the
    resolver shapes themselves are pinned on synthetic modules in
    `TestThePushScanResolvesTheLocalShapes`.
    """

    def test_the_real_tree_leaves_exactly_these_unresolved_sites(self, hud):
        lens = hud._lens_module()
        files = lens._sources()
        _roots, reachable = lens._closure(
            lens._import_graph(files), {lens._module_name(p) for p in files})
        _pushed, unresolved = hud._pushed_types(reachable)
        assert len(unresolved) == 5, (
            f"the REAL tree's unresolved push-site count changed "
            f"({len(unresolved)} != 5): {sorted(unresolved)} — if the resolver "
            "improved, verify each remaining site genuinely cannot be resolved "
            "locally and move this pin DOWN; if it grew, find what regressed")
        modules = sorted({u.rsplit(":", 1)[0] for u in unresolved})
        assert modules == [
            "ai_brain.server.intro_live",    # heard() returns the offer OR the
                                             # kept card — genuinely undecided
            "ai_brain.server.lens_hosts",    # candor/veritas/saga: the producing
                                             # calls live in other modules
            "ai_brain.server.server",        # the self-test's function-parameter
                                             # card (inter-procedural)
            # truth_live left this list on 2026-08-02. Its `_push` BUILDS the
            # card rather than forwarding one, so the inner push_event is the
            # site, and `to_gauge_card` — a builder call assigned to a local,
            # mutated, then returned — is read by `_fn_card_types_found` now.
        ], (
            "the REAL tree's unresolved push sites moved modules: "
            f"{modules} (from {sorted(unresolved)})")


class TestTheGlassIsTheONETheBrainCanReach:
    """The correction that mattered most, and the one a green checker hid.

    An earlier draft asked only "does `halo-lua` draw this type" and answered
    yes for all 24. But `Brain.push_event` fans out to the LIVE LENS — an SSE
    stream to the browser page in `live.py` — and for a long time nothing under
    `ai_brain/` called `bridge.send_card`, so no Brain push had any path to the
    glasses firmware at all. The checker was measuring the Orchestrator's
    renderer to decide whether the Brain's cards were visible.

    **That gap closed on 2026-08-02** (`ai_brain/server/halo_link.py`). The two
    renderers are still measured separately — they draw different sets and
    always will — but "the Brain cannot reach the device" is no longer true, and
    the assertion below is inverted to say so.
    """

    def test_the_brain_reaches_the_device_renderer_through_exactly_one_seam(self):
        """RETIRED, inverted. This asserted `not hits` — that NOTHING under
        `ai_brain/` called `send_card`.

        The whole `bridge/` package, including the real BLE transport, was
        constructed only by `main.py`'s emulator helper and `simulator/`, both
        hanging off the `Orchestrator` the shipped Brain never builds
        (decisions/0001). So the transport was complete, tested, and reachable
        only from code the wearer does not run — the same defect as
        `persona_tuning`, `typed_models` and `memory_dedup`, and the largest,
        because it is why nothing reached the glass.

        The inversion keeps the property that made the original valuable: the
        path must be ONE seam, not scattered `send_card` calls across the
        producers. A single subscriber on the existing fan-out means every card
        the Live Lens gets the glass gets; twenty call sites would mean twenty
        chances to forget, and this test would stop being able to tell whether
        any given card reaches the device.
        """
        import pathlib
        import subprocess
        root = pathlib.Path(__file__).resolve().parents[4]
        hits = [ln for ln in subprocess.run(
            ["grep", "-rn", "send_card",
             str(root / "host-python/src/dreamlayer/ai_brain")],
            capture_output=True, text=True).stdout.strip().splitlines() if ln]
        files = {ln.split(":", 1)[0].rsplit("/", 1)[-1] for ln in hits}
        assert files == {"halo_link.py"}, (
            "the Brain's path to the glasses must stay a single seam; "
            f"send_card is now called from {sorted(files)}")

    def test_the_two_renderers_are_measured_separately(self, hud):
        device = hud._drawn_on_glass()
        live = hud._drawn_on_live_lens()
        assert device and live
        # RETIRED, inverted — this asserted `len(live) < len(device)`.
        #
        # The Live Lens WAS the smaller set: 30 bespoke branches against
        # halo-lua's 45, so fifteen of the forty card types `hud/cards.py`
        # builds fell through to `glassEventCard` and arrived on the phone with
        # the field carrying their answer dropped. Fourteen of those fifteen
        # already drew properly on the glasses, which made the phone the
        # surface that was behind.
        #
        # All fifteen have bespoke renderers as of 2026-08-02, so the sets are
        # level at 45. The original's own failure message said to check the
        # scan was not matching comments if this ever happened — it was
        # checked: every one of the 45 has a real `t === "X"` dispatch arm, and
        # `test_live_lens_card_parity.py` pins each by name.
        assert len(live) >= len(device) - 1, (
            f"the Live Lens fell behind again ({len(live)} vs {len(device)} on "
            "the device) — a card type the Brain builds is drawing generically "
            "on the phone")
        # NOT a subset, and the exceptions are the point rather than slack in
        # the test: a card the Brain pushes but the ORCHESTRATOR never sends has
        # no reason to exist in halo-lua, so the Live Lens is the only surface
        # that can draw it. Each one here must be a type the Brain actually
        # pushes — anything else means a branch was added for a card that never
        # arrives, which is the same wasted-wiring mistake in the other
        # direction.
        lens = hud._lens_module()
        files = lens._sources()
        _roots, reachable = lens._closure(
            lens._import_graph(files), {lens._module_name(p) for p in files})
        pushed, _unresolved = hud._pushed_types(reachable)
        brain_only = live - device
        # This used to assert `brain_only` was NON-empty, naming ConsistencyCard,
        # StasisCard and QuestRewardCard as pushed-but-undrawn on the device.
        # All three got device renderers on 2026-08-02 (renderer.lua:
        # draw_consistency / draw_quest_reward / draw_stasis), which is the
        # whole point of the Brain gaining a path to the glass — so an EMPTY set
        # is now the good outcome and the assertion is inverted.
        #
        # The invariant that made the original valuable survives: whatever is
        # here must be a type something actually pushes, or a branch was added
        # for a card that never arrives.
        for ctype in brain_only:
            assert ctype in pushed or ctype in hud._BRAIN_ONLY_PUSHED, (
                f"{ctype} has a Live Lens branch but nothing pushes it — "
                "either wire the push or drop the branch.")
        for ctype in ("ConsistencyCard", "StasisCard", "QuestRewardCard"):
            assert ctype in device, (
                f"{ctype} lost its device renderer — the Brain pushes it and "
                "the glasses would fall back to draw_fallback")

    def test_the_generic_fallback_is_not_counted_as_a_drawing(self, hud):
        """`glassEventCard` draws `eyebrow` and `primary` only. Counting it
        would mark every card as rendered on a surface that silently drops the
        field carrying the answer."""
        live = hud._drawn_on_live_lens()
        assert "HarkCard" in live           # has a real branch
        # The negative case has rotated twice, and the reason is the point.
        # First ReadyCard gained a branch, so ErrorCard took its place. Now
        # ErrorCard, PaletteShiftCard and QueryListeningCard all have branches
        # too — every one of the forty types `hud/cards.py` builds does, as of
        # 2026-08-02.
        #
        # So the guard can no longer be "a built type with no branch": there
        # aren't any, and inventing one would mean leaving a card drawing
        # generically on the phone purely to keep a test honest. What it CAN
        # still prove is that the scan reads dispatch arms rather than names:
        # `ObjectPanelCard` appears in this file and has no arm.
        assert "ObjectPanelCard" not in live, (
            "the scan has degenerated into 'any card name in the file' — it "
            "must read `t === \"X\"` dispatch arms, or the generic fallback "
            "starts counting as a drawing again")
        # …and every name it DOES report must have a real arm.
        import re as _re
        from dreamlayer.ai_brain.server import live as _live_mod
        missing = [c for c in sorted(live)
                   if not _re.search(r't === "%s"\s*(\|\||\))' % c,
                                     _live_mod._PAGE)]
        assert not missing, f"reported without a dispatch arm: {missing}"

    def test_the_card_whose_answer_needs_a_branch_has_one(self, hud):
        """ObjectRecallCard puts the place — the entire answer — outside
        `primary`. Wiring the producer without the renderer branch ships a card
        that echoes the question back."""
        assert "ObjectRecallCard" in hud._drawn_on_live_lens()


# ---------------------------------------------------------------------------
# The capability checker, held to the same standard
# ---------------------------------------------------------------------------

CAP_SCRIPT = (pathlib.Path(__file__).resolve().parents[4]
              / "scripts" / "capability_reachability.py")


@pytest.fixture(scope="module")
def caps():
    if not CAP_SCRIPT.exists():
        pytest.skip("checker not on disk")
    spec = importlib.util.spec_from_file_location("_cap_reachability", CAP_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def closure(caps):
    """(lens module, reachable set) — computed ONCE for this file.

    Walking the import graph over ~390 modules is the expensive part of every
    test here, and each test that recomputed it paid the full cost again. Held at
    module scope because the graph is derived from files on disk and no test
    mutates it.
    """
    lens = caps._lens_module()
    files = lens._sources()
    _roots, reachable = lens._closure(
        lens._import_graph(files), {lens._module_name(p) for p in files})
    return lens, reachable


@pytest.fixture(scope="module")
def buckets(caps, closure):
    lens, reachable = closure
    return caps.classify(lens, reachable)


class TestTheCapabilityCheckerSeesTheWholeCatalogue:

    def test_it_reads_every_declared_capability(self, caps):
        """68 today. The count matters because the handoff said ~39 for months
        — a checker reading half the catalogue would have agreed with it.

        This is a PARSER floor, not a catalogue-size freeze. It fell 74 -> 68 as
        six entries were deliberately retired (`asr_alignment`, `facial_aus`,
        `skia_render`, `memory_dedup`, `frame_glasses`, and earlier
        `causal_fusion`), each recorded with an inverted test. Lower it when an
        entry is retired on purpose; never lower it to make a red run go green,
        because the failure this guards is the checker silently reading half the
        file.
        """
        decl = caps._declared_caps()
        assert len(decl) >= 68, f"only {len(decl)} capabilities parsed"

    def test_every_capability_names_a_seam_or_is_a_documented_concept(self, caps):
        """`seam` is the only field that makes this checkable at all. One entry
        legitimately has none (`folder_sync` is a Syncthing recipe, not an
        adapter); a second would mean the field is being left blank."""
        blank = [k for k, _, _, s in caps._declared_caps() if not s.strip()]
        assert not blank, f"capabilities with no seam recorded: {blank}"

    def test_a_prose_seam_still_yields_its_paths(self, caps):
        """Seams are prose with paths in them. A parser that wanted a bare path
        would silently drop the multi-file ones and call them unreachable."""
        mods = caps._seam_modules(
            "memory/vector_store.py (+chroma/lance/usearch siblings)")
        assert mods == ["dreamlayer.memory.vector_store"], mods
        two = caps._seam_modules(
            "orchestrator/commitment_nlp.py, social_lens/ner_spacy.py")
        assert len(two) == 2, two

    def test_the_by_design_bucket_is_a_claim_not_a_catch_all(self, caps):
        """Every reason string has to say something. An empty or generic reason
        turns the bucket into a place to hide gaps, which is the one thing it
        must not become."""
        for prefix, why in caps._BY_DESIGN:
            assert prefix and len(why) > 20, (prefix, why)

    def test_an_orchestrator_seam_is_not_by_design_any_more(self, caps):
        """The inversion. `_BY_DESIGN` used to carry an `orchestrator/` prefix,
        so eleven capabilities were filed as settled decisions on a PATH RULE —
        including `nlp`, the only impact-5 entry there is. "Its consumer is the
        Orchestrator" is the reason eight capabilities were re-hosted Brain-side,
        not a reason to stop looking. They live in `_NOT_YET_HOSTED` now, each
        with the wearer-facing loss written out, and the report prints them as
        real work."""
        assert not caps._by_design("orchestrator/wakeword.py")
        assert not caps._not_yet("memory/doc_schema.py")

    def test_the_not_yet_bucket_says_what_the_wearer_loses(self, caps):
        """EMPTY as of 2026-08-03, and it got there by every entry being BUILT.

        The assertion inverts rather than being deleted. What still has to hold
        is the BAR: a key here must carry a real user-facing loss, because a
        blank or generic string turns the bucket back into the place to hide
        gaps that `_BY_DESIGN` had become. The next capability whose only
        consumer is the Orchestrator lands here and has to say what it costs."""
        for key, why in caps._NOT_YET_HOSTED.items():
            assert key and len(why) > 20, (key, why)

    def test_the_mechanism_survives_the_bucket_emptying(self, caps):
        """A checker whose interesting bucket is empty is one nobody notices
        has stopped working. `_not_yet` must still resolve a key it is given,
        and the bucket must still be collected and printed."""
        import sys
        assert caps._not_yet("anything") == ""       # nothing is filed today
        caps._NOT_YET_HOSTED["_probe"] = (
            "a placeholder loss long enough to clear the bar")
        try:
            assert caps._not_yet("_probe")
            monkey = sys.argv
            sys.argv = ["capability_reachability.py"]
            try:
                assert caps.main() == 0
            finally:
                sys.argv = monkey
        finally:
            caps._NOT_YET_HOSTED.pop("_probe", None)

    def test_a_key_leaves_the_not_yet_bucket_only_by_being_built(self, caps):
        """`nlp` was the first out. It must not have been quietly moved to
        `_BY_DESIGN` — that would be the reclassification this split exists to
        make impossible — and it must now be genuinely driven."""
        assert "nlp" not in caps._NOT_YET_HOSTED
        assert not caps._by_design(
            "orchestrator/commitment_nlp.py, social_lens/ner_spacy.py")
        from dreamlayer.capabilities import _PROMOTED_AT_RUNTIME
        assert "nlp" in _PROMOTED_AT_RUNTIME

    def test_the_dormant_set_is_read_from_capabilities_not_hardcoded(self, caps):
        """`_NOT_WIRED` is the product's own honest-status list. Reading it is
        what stopped the OPEN bucket printing 19 capabilities as "no reason on
        file" when 18 of them are named there with the reason written out."""
        dormant = caps._declared_dormant()
        assert len(dormant) >= 15, f"only {len(dormant)} parsed — set literal?"
        # `memory_dedup` used to be named here and was retired on 2026-08-02:
        # near-duplicate collapsing needs no dependency, so there is nothing to
        # install and nothing to declare dormant.
        for key in ("typed_docs", "social_graph", "live_interpret"):
            assert key in dormant, key
        assert "vector_search" not in dormant     # wired; must stay checkable

    def test_nothing_is_misreported_as_available(self, buckets):
        """The bucket that matters: a seam no Brain path can load, on a
        capability the catalog will still light up once its extras install.
        Zero is the only acceptable value — anything here is a false green
        shown to the wearer."""
        assert not buckets["open_gaps"], (
            "capabilities whose seam the Brain cannot load and which are not "
            f"declared dormant — each is a false green: {buckets['open_gaps']}")

    def test_the_vector_search_seam_names_the_file_the_brain_opens(self, caps, closure):
        """The one stale seam string this pass found. `vector_store.py` sits
        behind the Orchestrator; the Brain's recall paths construct
        `PersistentAnnIndex` from `memory/ann_index.py`. Naming the wrong file
        made a shipping capability read as unreachable."""
        _lens, reachable = closure
        seam = next(s for k, _t, _c, s in caps._declared_caps()
                    if k == "vector_search")
        mods = caps._seam_modules(seam)
        assert any(m in reachable for m in mods), (seam, mods)


class TestLoadableIsNotOneState:
    """The correction that dropped the headline from 42 to 30.

    "The seam is in the Brain's import closure" answers *can this file load*.
    It was being read as *the Brain uses this*, which is the same conflation
    `lens_reachability.py` warns about in its own header — and the reason this
    script's good column contained eleven capabilities the product's own
    `_NOT_WIRED` list calls unwired, plus one whose only class was constructed
    by nothing but a test.
    """

    def test_public_names_finds_what_a_seam_defines(self, caps, tmp_path):
        p = tmp_path / "seam.py"
        p.write_text("class Thing:\n    pass\n\n\ndef helper():\n    pass\n"
                     "\n\ndef _private():\n    pass\n", encoding="utf-8")
        assert caps._public_names(p) == {"Thing", "helper"}

    def test_public_names_skips_underscored_definitions(self, caps, tmp_path):
        """A `_private` name being referenced elsewhere would not mean the seam
        is used — it would mean somebody reached inside it."""
        p = tmp_path / "seam.py"
        p.write_text("class _Hidden:\n    pass\n", encoding="utf-8")
        assert caps._public_names(p) == set()

    def test_public_names_survives_a_file_it_cannot_parse(self, caps, tmp_path):
        p = tmp_path / "broken.py"
        p.write_text("def (:\n", encoding="utf-8")
        assert caps._public_names(p) == set()          # no crash, no finding

    def test_nested_definitions_are_not_counted_as_exports(self, caps, tmp_path):
        """Only module-level names are importable. A method named in another file
        is a coincidence of vocabulary, not a reference to this seam."""
        p = tmp_path / "seam.py"
        p.write_text("class Thing:\n    def method(self):\n        pass\n",
                     encoding="utf-8")
        assert caps._public_names(p) == {"Thing"}

    def _stub_lens(self, tmp_path, files: dict):
        """A `lens` with just the two methods `_referenced_outside` uses, over
        files this test wrote. Synthetic because the real tree cannot exhibit a
        near-miss on demand — and a near-miss is the case that matters."""
        paths = {}
        for name, body in files.items():
            p = tmp_path / f"{name}.py"
            p.write_text(body, encoding="utf-8")
            paths[name] = p

        class _Lens:
            @staticmethod
            def _sources():
                return list(paths.values())

            @staticmethod
            def _module_name(p):
                return p.stem
        return _Lens

    def test_a_name_that_merely_contains_the_export_is_not_a_reference(
            self, caps, tmp_path):
        """`SomeThingElse` is not a use of `Thing`. Without a word boundary the
        match is a substring search, which can only ever report MORE things as
        used — so it fails silently, by finding no defects, which is the exact
        direction this checker has already been wrong in twice.

        All four near-misses, because three separate mutations of that one
        pattern each survive a test that only covers some of them: a suffix
        collision (`Thingummy`) needs the TRAILING boundary, a prefix collision
        (`MyThing`) needs the LEADING one, an infix (`SomeThingElse`) needs
        either, and a collision on the second exported name (`xhelper`) is what
        catches an alternation that lost its group — `\\bA|B\\b` anchors only the
        first alternative and only at the front.
        """
        lens = self._stub_lens(tmp_path, {
            "seam": "class Thing:\n    pass\n\n\ndef helper():\n    pass\n",
            "caller": ("x = SomeThingElse()\n"
                       "Thingummy = 1\n"
                       "y = MyThing\n"
                       "q = xhelper\n"
                       "r = helperish(2)\n"),
        })
        assert caps._referenced_outside(
            lens, {"seam", "caller"}, ["seam"]) is False

    def test_a_real_reference_to_the_export_is_found(self, caps, tmp_path):
        """The control for the test above, so the boundary cannot just be "never
        matches"."""
        lens = self._stub_lens(tmp_path, {
            "seam": "class Thing:\n    pass\n",
            "caller": "from .seam import Thing\nx = Thing()\n",
        })
        assert caps._referenced_outside(
            lens, {"seam", "caller"}, ["seam"]) is True

    def test_the_seam_itself_is_not_counted_as_a_caller(self, caps, closure):
        """A module names what it defines, always. Counting that would make
        every seam self-justifying and the bucket permanently empty."""
        lens, reachable = closure
        mods = caps._seam_modules("ai_brain/exo_cluster.py")
        by_mod = {lens._module_name(p): p for p in lens._sources()}
        assert mods[0] in by_mod, mods
        # with the seam as the ONLY reachable module, nothing outside it exists
        assert caps._referenced_outside(lens, {mods[0]}, mods) is False

    def test_a_seam_defining_nothing_is_not_a_finding(self, caps, closure):
        """No exported names means no evidence either way. The checker stays
        quiet rather than inventing a defect out of an absence."""
        lens, reachable = closure
        assert caps._referenced_outside(lens, reachable, ["dreamlayer.nope"]) is True

    def test_a_used_seam_is_found_to_be_used(self, caps, closure):
        """The control. `memory/ann_index.py` defines `PersistentAnnIndex`, which
        the Brain's recall paths construct — if this reported unconstructed the
        check would be measuring nothing."""
        lens, reachable = closure
        mods = caps._seam_modules("memory/ann_index.py")
        assert caps._referenced_outside(lens, reachable, mods) is True

    def test_no_capability_is_loadable_and_unconstructed(self, buckets):
        """`ai_brain/exo_cluster.py` was the whole reason this bucket exists:
        importable, in the closure, honestly reporting "external" — and
        `ExoClusterBackend` constructed by nothing but its own unit test, so no
        Brain path could reach an exo cluster on the wearer's own machines. It is
        wired to `_wire_model` now; this keeps the next one from hiding."""
        assert not buckets["unconstructed"], (
            "capabilities whose seam loads but which nothing names — a green "
            f"line no code path can reach: {buckets['unconstructed']}")

    def test_the_dormant_declaration_outranks_loadability(self, caps, buckets):
        """The ordering bug itself. Eleven capabilities are BOTH importable and
        named in `_NOT_WIRED`; because loadability was tested first they sat in
        the good column while the product told the wearer they were dormant. The
        product's own honesty list has to win."""
        dormant = caps._declared_dormant()
        leaked = [k for k, _t, _s in buckets["ok"] if k in dormant]
        assert not leaked, (
            f"declared-dormant capabilities counted as working: {leaked}")
        assert len(buckets["conditional"]) + len(buckets["driven"]) >= 5, (
            "the loadable-and-dormant buckets emptied out — either the ordering "
            "regressed or `_NOT_WIRED` was gutted")

    def test_runtime_promotion_is_read_from_both_mechanisms(self, caps):
        """`DL_WIRED_<KEY>` gets set two ways and a checker that knew only one
        would file a driven capability as inert work-to-do.

        A promoted-caps tuple (`ear.py:EAR_CAPS`) is turned into flags in a loop,
        so no literal flag name appears anywhere; `social_graph` has no start/stop
        event to hang a durable flag on and is computed per capability report, as a
        literal. Both are read."""
        promoted = caps._runtime_promoted()
        assert "mic_capture" in promoted, "the EAR_CAPS tuple was not read"
        assert "live_interpret" in promoted
        for key in ("social_graph", "dream_style", "crdt_sync"):
            assert key in promoted, f"the literal flag for {key} was not read"
        # and not everything — a set that swallowed the catalogue would empty the
        # inert bucket and hide the real shortlist.
        #
        # This used to name `coreml_ondevice`, which is promoted now: its
        # `__call__` was `return None if not (...) else None` and is a real ANE
        # classifier. The guard needs a capability that genuinely has NO
        # promoter, so it names the ones still in that bucket — and if they are
        # ever wired, this line has to move again rather than being deleted,
        # because a non-vacuity guard that stops guarding is worse than none.
        assert "asgi_server" not in promoted
        assert "structured_output" not in promoted
        assert "asgi_server" not in promoted

    def test_a_test_setting_a_flag_does_not_count_as_promotion(self, caps):
        """Tests set `DL_WIRED_*` to exercise the meter. Reading those would let a
        capability look driven because something MOCKED it being driven — the
        importable-never-called trap wearing a different hat."""
        src = CAP_SCRIPT.read_text(encoding="utf-8")
        i = src.index("def _runtime_promoted")
        assert '"/tests/"' in src[i:i + 2000]

    def test_the_driven_and_inert_buckets_are_disjoint_and_both_populated(self, buckets):
        """The split is the point. If either side empties, the report has gone back
        to reporting "loadable and dormant" as one undifferentiated list."""
        driven = {k for k, _t, _s in buckets["driven"]}
        inert = {k for k, _t, _s in buckets["conditional"]}
        assert driven and inert, (driven, inert)
        assert not (driven & inert)

    def test_every_capability_lands_in_exactly_one_bucket(self, buckets):
        """Six buckets and a headline count only mean something if they
        partition the catalogue. A key in two buckets double-counts; a key in
        none disappears from the audit entirely."""
        names = ("ok", "unconstructed", "conditional", "driven", "open_gaps",
                 "dormant", "expected", "not_yet", "concepts")
        seen: dict = {}
        for name in names:
            for row in buckets[name]:
                seen.setdefault(row[0], []).append(name)
        dupes = {k: v for k, v in seen.items() if len(v) > 1}
        assert not dupes, f"capabilities in more than one bucket: {dupes}"
        missing = {k for k, _t, _c, _s in buckets["caps"]} - set(seen)
        assert not missing, f"capabilities in no bucket at all: {missing}"

    def test_the_headline_counts_only_the_good_bucket(self, caps, buckets,
                                                      capsys, monkeypatch):
        """It read "42 with a seam the Brain can load" while eleven of the 42
        were declared unwired. The printed number has to be the `ok` bucket and
        nothing else, or the summary line contradicts the detail below it.

        Checked against the actual output rather than the source: the two got out
        of step once already, which is the only way this can go wrong."""
        monkeypatch.setattr(sys, "argv", ["capability_reachability.py"])
        assert caps.main() == 0
        head = capsys.readouterr().out.splitlines()[0]
        n = int(head.split()[0])
        good = int(head.split("·")[1].strip().split()[0])
        assert n == len(buckets["caps"]), head
        assert good == len(buckets["ok"]), head
        assert good < n, "the good column cannot be the whole catalogue"


class TestThePushScanKnowsBuiltFromPushed:
    """The distinction the UNDECLARED bucket turns on.

    Ten card types are built outside `hud/cards.py` by Brain-reachable code.
    Only the ones handed to `_push`/`push_event` can ever meet the Live Lens's
    generic renderer; the rest are returned as JSON to the phone, where every
    field survives. A scan that reported "built" as "pushed" invented seven
    defects that do not exist.
    """

    def _reachable(self, hud):
        lens = hud._lens_module()
        files = lens._sources()
        _roots, reachable = lens._closure(
            lens._import_graph(files), {lens._module_name(p) for p in files})
        return reachable

    def test_it_finds_the_pushes_it_can_name(self, hud):
        pushed, _unresolved = hud._pushed_types(self._reachable(hud))
        assert "StasisCard" in pushed          # lens_hosts freeze/resume
        assert "SavedMemoryCard" in pushed     # lens_hosts pin
        assert "ObjectRecallCard" in pushed    # brain_waypath locate

    def test_json_only_cards_are_not_reported_as_pushed(self, hud):
        """`QuestCard` and `SocialLensCard` are returned to the phone and never
        pushed. If they start showing as pushed, the resolver has begun
        guessing — which is how `WaypathCard` was once reported pushed off a
        name collision."""
        pushed, _unresolved = hud._pushed_types(self._reachable(hud))
        for ctype in ("QuestCard", "SocialLensCard", "WaypathCard"):
            assert ctype not in pushed, ctype

    def test_an_ambiguous_name_refuses_to_resolve(self, hud):
        """`to_hud_card` is defined nine times across the tree, returning a
        different card type each. Resolving it by bare name reported
        QuestRewardCard as never-pushed and WaypathCard as pushed — both
        exactly backwards."""
        fn_types = hud._fn_card_types(self._reachable(hud))
        assert fn_types.get("to_hud_card", "") == "", (
            "an ambiguous function name resolved to a single card type")
        assert fn_types.get("saved_memory") == "SavedMemoryCard"

    def test_the_pusher_is_not_counted_as_a_push_site(self, hud):
        """`_push`'s own body forwards to `push_event`. Counting that as a call
        site produced an unresolvable entry on every run."""
        _pushed, unresolved = hud._pushed_types(self._reachable(hud))
        assert not any(":800" in u and "lens_hosts" in u for u in unresolved)

    def test_the_blind_spot_is_declared_rather_than_silent(self, hud):
        """The real pushes that defeat a one-hop resolver are listed, not
        dropped — and each must still be a type something actually builds."""
        assert hud._BRAIN_ONLY_PUSHED
        inline = hud._inline_card_types(self._reachable(hud))
        for ctype in hud._BRAIN_ONLY_PUSHED:
            assert ctype in inline, f"{ctype} is declared pushed but unbuilt"

    def test_a_one_argument_pusher_is_not_skipped_in_silence(self, hud):
        """The shape that hid two whole push sites.

        `push_event(kind, card)` is the dominant signature, so the resolver read
        `args[1]` and treated a ONE-argument call as "not our pusher" — the
        escape hatch for `brain_rc`'s unrelated deployer. But `IntroHost._push(card)`
        and `TruthRead._push(result)` are one argument and ours, so both fell
        through it: not resolved, not reported, invisible. Which argument holds
        the card is now read from the pusher's own definition in the same module.
        """
        pushed, unresolved = hud._pushed_types(self._reachable(hud))
        assert "IntroKeptCard" in pushed, (
            "a one-argument `self._push(card)` was dropped again")
        # RETIRED, inverted. This asserted truth_live stayed UNRESOLVED, on the
        # grounds that `TruthRead._push` takes a result rather than a card.
        # True of the outer call — and the type was decidable one line inside,
        # where `_push` does `card = result.to_gauge_card()` and pushes it.
        # `_push` wrappers that BUILD rather than forward are scanned now, and
        # `to_gauge_card` (a builder call assigned to a local, mutated, then
        # returned) is read by `_fn_card_types_found`.
        assert not any("truth_live" in u for u in unresolved), (
            "truth_live went back to unresolvable — check the builder/forwarder "
            "split in `_pushed_types` and the return-a-local shape in "
            "`_fn_card_types_found`")
        assert "TruthLensCard" in pushed, (
            "truth_live resolves but does not name TruthLensCard")

    def test_the_deployers_same_named_method_is_still_not_a_push(self, hud):
        """`brain_rc` calls `.push_event(name)` on a deployer that has nothing
        to do with the glass. The new rule keys on the module DEFINING a pusher
        of that arity, and brain_rc defines none, so it stays out."""
        _pushed, unresolved = hud._pushed_types(self._reachable(hud))
        assert not any("brain_rc" in u for u in unresolved)

    def test_a_card_built_inline_at_the_push_site_resolves(self, hud):
        """Reading a literal `"type"` is reading, not inference — and it is the
        only reason `IntroKeptCard` can be named at all, since the function that
        hands it over (`confirm`) builds the dict right there rather than
        calling a `hud/cards.py` builder."""
        pushed, _u = hud._pushed_types(self._reachable(hud))
        assert pushed.get("IntroKeptCard") == {
            "dreamlayer.ai_brain.server.intro_live"}

    def test_the_ambiguous_intro_site_still_refuses(self, hud):
        """`IntroductionCapture.heard` returns the offer card OR the kept one
        depending on `intro_auto_keep`, so the type genuinely is not decided at
        that line. Declared in `_BRAIN_ONLY_PUSHED`, never guessed."""
        _pushed, unresolved = hud._pushed_types(self._reachable(hud))
        assert any("intro_live" in u for u in unresolved)
        assert "IntroOfferCard" in hud._BRAIN_ONLY_PUSHED


class TestTheLiveLensDrawsWhatTheBrainPushes:
    """The Live Lens is the ONLY surface a Brain push reaches. A card type it
    lacks a branch for is drawn by `glassEventCard` — eyebrow and primary,
    nothing else — so for these cards a missing branch deletes the answer."""

    def _live_src(self):
        p = (pathlib.Path(__file__).resolve().parents[1]
             / "ai_brain" / "server" / "live.py")
        return p.read_text(encoding="utf-8")

    def test_every_pushed_card_type_has_a_branch(self, hud):
        lens = hud._lens_module()
        files = lens._sources()
        _roots, reachable = lens._closure(
            lens._import_graph(files), {lens._module_name(p) for p in files})
        pushed, _unresolved = hud._pushed_types(reachable)
        live = hud._drawn_on_live_lens()
        missing = sorted((set(pushed) | hud._BRAIN_ONLY_PUSHED) - live)
        assert not missing, (
            "card types the Brain pushes with no Live Lens branch — each one "
            f"renders as eyebrow+primary and loses the rest: {missing}")

    def test_the_consistency_branch_draws_the_prior_statement(self):
        """Candor's whole proposition is the FOOTER — the thing you said
        before. Drawn without it, the card is an accusation with the evidence
        removed, which is worse than not drawing it at all."""
        src = self._live_src()
        i = src.index("function glassConsistencyCard")
        body = src[i:i + 2200]
        assert "c.footer" in body and "prior_summary" in body

    def test_the_drift_branch_draws_decay_and_the_due_date(self):
        """`decay` and `due` are what make the card actionable; the generic
        path kept only the state word and the task."""
        src = self._live_src()
        i = src.index("function glassDriftCard")
        body = src[i:i + 2200]
        assert "c.decay" in body and ("c.due" in body or "c.footer" in body)

    def test_the_stasis_branch_draws_the_freshness_footer(self):
        """On resume, `footer` is how long the thought has been held — the
        field that says whether it is still the one you put down."""
        src = self._live_src()
        i = src.index("function glassStasisCard")
        body = src[i:i + 2000]
        assert "c.footer" in body

    def test_the_reward_branch_names_the_reward(self):
        """`primary` is "+120 XP"; `detail` carries the rank and level. Without
        detail the card is a bare number."""
        src = self._live_src()
        i = src.index("function glassQuestRewardCard")
        body = src[i:i + 2200]
        assert "c.detail" in body

    def test_the_inline_script_still_parses(self):
        """A 2,700-line inline script with no build step: one stray brace ships
        a blank Live Lens with no error anywhere on the Python side. Skipped
        rather than faked when node is unavailable."""
        import shutil
        import subprocess
        import tempfile
        node = shutil.which("node")
        if not node:
            pytest.skip("node not available")
        src = self._live_src()
        start = src.index("<script__NONCE__>") + len("<script__NONCE__>")
        end = src.index("</script>", start)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(src[start:end])
            path = f.name
        try:
            r = subprocess.run([node, "--check", path],
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[:2000]
        finally:
            pathlib.Path(path).unlink(missing_ok=True)

    def test_a_card_that_says_it_stays_is_not_expired(self):
        """`dismiss_ms: 0` is the card contract for STAYS UNTIL REPLACED, used
        by five builders. Every call site passes `c.dismiss_ms || <fallback>`,
        which turned 0 into the fallback — so a "Listening…" ring vanished
        after 4.2s with the microphone still open, and the card said the
        opposite of the truth."""
        src = self._live_src()
        i = src.index("function gend(ms)")
        body = src[i:i + 900]
        assert "if (ms === 0) return;" in body
        # …and the two cards that depend on it must not re-introduce the `||`
        for fn in ("glassListeningCard", "glassCaptionCard"):
            j = src.index("function " + fn)
            seg = src[j:src.index("\n}", j)]
            assert "c.dismiss_ms ||" not in seg, fn

    def test_the_pulse_cannot_outlive_its_card(self):
        """The Listening ring is the one card here that animates. Its interval
        has to die when anything else paints the canvas, or it repaints the ring
        over whichever lens result landed next."""
        src = self._live_src()
        i = src.index("function glassCtx()")
        assert "clearInterval(glassAnim)" in src[i:i + 700]
        j = src.index("function glassClear()")
        assert "clearInterval(glassAnim)" in src[j:j + 300]

    def test_no_producible_card_is_left_on_the_generic_renderer(self, hud):
        """The bucket the script PRINTS but does not fail on — and the gap a
        mutation run found. Deleting the `FactCheckCard` dispatch arm moved it
        into "generic on the Live Lens" and every test still passed, because
        `_pushed_types` cannot name that push (`self._push("fact_check",
        res.card)` hands it an attribute) and the exit code ignores the bucket.

        A card with a Brain-side producer that lands on `glassEventCard` loses
        every field but eyebrow and primary — for FactCheckCard that is the
        BASIS, i.e. the difference between a fact-check and an accusation. The
        bucket is empty today and this keeps it there."""
        features = hud._declared_features()
        samples = hud._sample_builders()
        types = hud._card_types()
        lens = hud._lens_module()
        files = lens._sources()
        _roots, reachable = lens._closure(
            lens._import_graph(files), {lens._module_name(p) for p in files})
        producers = hud._producers(reachable, set(samples.values()))
        live = hud._drawn_on_live_lens()

        gutted = []
        for _fid, title, key in features:
            builder = samples.get(key)
            ctype = types.get(builder or "", "")
            if not producers.get(builder or "") or not ctype:
                continue                       # no producer: a different bucket
            if ctype not in live:
                gutted.append(f"{title} ({ctype})")
        assert not gutted, (
            "cards the Brain can produce that the Live Lens draws generically "
            f"— each loses every field but eyebrow+primary: {gutted}")


# ---------------------------------------------------------------------------
# The dependency checker: does installing the declared module change anything?
# ---------------------------------------------------------------------------

DEP_SCRIPT = (pathlib.Path(__file__).resolve().parents[4]
              / "scripts" / "capability_dependency.py")


@pytest.fixture(scope="module")
def dep():
    if not DEP_SCRIPT.exists():
        pytest.skip("checker not on disk")
    spec = importlib.util.spec_from_file_location("_cap_dependency", DEP_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dep_buckets(dep):
    return dep.classify()


def _by_mod(tmp_path, files: dict):
    """A {dotted name: path} map over files this test wrote — the same shape
    `_package_modules()` returns for the real tree, so `_classify_module`
    cannot tell the difference."""
    out = {}
    for dotted, body in files.items():
        p = tmp_path / (dotted.replace(".", "__") + ".py")
        p.write_text(body, encoding="utf-8")
        out[dotted] = p
    return out


class TestTheDependencyCheckerReadsBindingsNotText:
    """`from X import Y` then using `Y` is real use, and the binding — not the
    module name — is what has to be found. A grep for the module name gets both
    directions wrong: it misses aliased use and it counts prose mentions."""

    def test_a_from_import_binding_that_is_called_is_use(self, dep, tmp_path):
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "from fakelib import thing\n\n\ndef go():\n"
                        "    return thing()\n",
        })
        bucket, why = dep._classify_module("fakelib", ["pkg.seam"], by_mod, {})
        assert bucket == "used", why
        assert "thing" in why

    def test_an_aliased_import_is_resolved_to_its_binding(self, dep, tmp_path):
        """`ImportFrom -> alias.asname or alias.name`. Only the AS name exists
        in code afterwards; matching the original would miss this."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "from fakelib import thing as th\n\nx = th(1)\n",
        })
        bucket, why = dep._classify_module("fakelib", ["pkg.seam"], by_mod, {})
        assert bucket == "used", why

    def test_a_submodule_import_binds_the_top_level_name(self, dep, tmp_path):
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "import fakelib.sub\n\nfakelib.sub.go()\n",
        })
        bucket, why = dep._classify_module("fakelib", ["pkg.seam"], by_mod, {})
        assert bucket == "used", why

    def test_a_comment_or_docstring_mention_is_not_use(self, dep, tmp_path):
        """The case `ast` gets right for free and a regex cannot. The module is
        named in the docstring, in a comment, and in a string literal — three
        mentions, zero references."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": '"""Adapter for fakelib — builds its engine elsewhere."""\n'
                        "import fakelib  # noqa: F401 — probe; fakelib is used by helper\n"
                        '_NOTE = "fakelib would go here"\n',
        })
        bucket, why = dep._classify_module("fakelib", ["pkg.seam"], by_mod, {})
        assert bucket == "probe", why

    def test_a_deliberately_planted_probe_only_fixture_is_caught(self, dep, tmp_path):
        """NON-VACUITY. A checker that reports "everything is fine" is
        indistinguishable from a broken one, so the suite plants a probe-only
        seam and requires the checker to catch it — the same lesson as
        `test_the_gap_is_closed_and_the_scan_could_still_see_one`."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "import deadweightlib  # noqa: F401\n\n_FLAG = True\n",
        })
        bucket, why = dep._classify_module(
            "deadweightlib", ["pkg.seam"], by_mod, {})
        assert bucket == "probe", why


class TestTheRealPathElsewhereIsFollowed:
    """The `pii_redaction` shape: the seam probes the module and builds the
    real thing one call away. A checker that flags this is crying wolf on
    correct code, which is worse than not having one."""

    def test_a_probe_with_a_real_path_elsewhere_is_indirect(self, dep, tmp_path):
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "import fakelib  # noqa: F401\n"
                        "from . import helper\n\n\n"
                        "def build():\n    return helper.engine()\n",
            "pkg.helper": "from fakelib import Engine\n\n\n"
                          "def engine():\n    return Engine()\n",
        })
        bucket, why = dep._classify_module("fakelib", ["pkg.seam"], by_mod, {})
        assert bucket == "indirect", why
        assert "pkg.helper" in why

    def test_an_intermediate_import_the_seam_never_calls_is_not_a_path(
            self, dep, tmp_path):
        """`from . import helper` that nothing references is itself just
        another probe. Following it would launder a probe-only module into the
        indirect bucket through a file the seam never calls — the protective
        property is NOT-INDIRECT, and it holds.

        The precise bucket here is "elsewhere", not "probe": helper.py is real
        code that genuinely imports and uses the dep, so 'nothing anywhere
        uses it' would be false — the use is simply unreachable from the seam
        (the import that would reach it is itself never referenced)."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "import fakelib  # noqa: F401\n"
                        "from . import helper  # noqa: F401\n",
            "pkg.helper": "from fakelib import Engine\n\n\n"
                          "def engine():\n    return Engine()\n",
        })
        bucket, why = dep._classify_module("fakelib", ["pkg.seam"], by_mod, {})
        assert bucket == "elsewhere", (
            f"the unreferenced intermediate import must NOT launder this into "
            f"indirect — got {bucket} ({why})")
        assert "pkg.helper" in why


class TestPiiRedactionIsNotCriedWolfOn:
    """The case the issue names as most of the work. `pii_presidio.py` imports
    `presidio_analyzer` as a bare probe and builds the engine through
    `nlp_setup.analyzer_engine()` — it genuinely uses the library, just
    indirectly, and the classification must say so."""

    def test_pii_redaction_is_used_indirectly_not_probe_only(self, dep, dep_buckets):
        rows = [r for r in dep_buckets["indirect"] if r[0] == "pii_redaction"]
        assert rows, (
            "pii_redaction left the indirect bucket — if the checker now calls "
            "it probe-only it is crying wolf on correct code; the buckets: "
            f"{ {k: len(v) for k, v in dep_buckets.items()} }")
        assert rows[0][1] == "presidio_analyzer"
        assert "nlp_setup" in rows[0][3], rows[0][3]

    def test_deleting_the_real_use_flips_it_off_indirect_and_back(
            self, dep, tmp_path):
        """The mutation check, both directions. The real use is the
        `from .. import nlp_setup` import plus the `nlp_setup.analyzer_engine()`
        call in the seam. Deleting them must flip `presidio_analyzer` OFF the
        indirect bucket — a checker that still says "indirect" is not reading
        call sites — and restoring the file must flip it back.

        The truthful post-mutation bucket is "elsewhere", not "probe":
        nlp_setup.py still genuinely imports and calls AnalyzerEngine (its
        other caller, person_guard.py, is untouched by this mutation), so
        "nothing anywhere uses it" would be false — the use is simply no
        longer reachable from THIS seam. The assertion therefore pins the
        more precise verdict; what the mutation must prove is unchanged:
        delete the call and the verdict moves, restore it and it returns."""
        seam = "dreamlayer.memory.pii_presidio"
        by_mod = dep._package_modules()
        real = by_mod[seam]
        src = real.read_text(encoding="utf-8")
        removed = ("            from .. import nlp_setup\n",
                   "            self._analyzer = nlp_setup.analyzer_engine()\n")
        for line in removed:
            assert line in src, "the seam changed shape; this mutation no " \
                "longer deletes the real use"
        mutated = src
        for line in removed:
            mutated = mutated.replace(line, "")
        p = tmp_path / "pii_presidio_mutated.py"
        p.write_text(mutated, encoding="utf-8")

        by_mod[seam] = p
        bucket, why = dep._classify_module(
            "presidio_analyzer", [seam], by_mod, {})
        assert bucket == "elsewhere", \
            f"with the real use deleted: {bucket} ({why})"
        assert "nlp_setup" in why, why

        by_mod[seam] = real
        bucket, why = dep._classify_module(
            "presidio_analyzer", [seam], by_mod, {})
        assert bucket == "indirect", f"with the file restored: {bucket} ({why})"
        assert "nlp_setup" in why

    def test_the_findings_the_issue_names_are_probe_only(self, dep, dep_buckets):
        """The live non-vacuity: the tree TODAY contains real probe-only
        entries, and a checker that stopped seeing them would read as a clean
        bill of health. If one of these gets wired (that is the hope — see the
        tracking issues), the fix is to wire it and update this assertion, the
        same retirement `test_the_gap_is_closed_and_the_scan_could_still_see_one`
        spells out.

        `("persona_tuning", "hulearn")` was RETIRED from this list on
        2026-08-02, which is the retirement working: `persona_humanlearn.tune`
        now calls `FunctionClassifier` for real, so the probe became a caller.
        Retire the others the same way when their turn comes — do not relax the
        assertion to keep them.
        """
        probe = {(k, m) for k, m, _s, _w in dep_buckets["probe"]}
        for entry in (("structured_output", "outlines"),
                      ("structured_output", "instructor"),
                      ("typed_pipeline", "pydantic_ai")):
            assert entry in probe, (
                f"{entry} is no longer probe-only — either it got wired "
                "(update this test) or the checker stopped reading seams")
        assert ("persona_tuning", "hulearn") not in probe, (
            "hulearn is probe-only again — persona_humanlearn stopped calling "
            "FunctionClassifier, so the capability is a claim once more")


class TestTheDependencyCheckerSeesTheWholeCatalogue:

    def test_it_reads_every_declared_capability(self, dep):
        decl = dep._declared_caps()
        assert len(decl) >= 68, f"only {len(decl)} capabilities parsed"
        # `kind="service"` capabilities legitimately declare () — nothing is
        # pip-installed, so there is no probe to audit. Everything else must
        # carry at least one module, or it would silently leave the audit.
        non_empty = [(k, modules) for k, _t, modules, _s in decl if modules]
        assert len(non_empty) >= 60, (
            f"only {len(non_empty)} capabilities with declared modules — "
            "entries are being dropped, not audited")

    def test_every_declared_module_lands_in_exactly_one_bucket(
            self, dep, dep_buckets):
        """The buckets only mean something if they partition the declared
        modules. A (cap, module) pair in two buckets double-counts; a pair in
        none disappears from the audit entirely."""
        rows = [r for name in ("used", "indirect", "elsewhere", "probe",
                               "no_seam")
                for r in dep_buckets[name]]
        declared = sorted((k, m) for k, _t, mods, _s in dep._declared_caps()
                          for m in mods)
        assert sorted((r[0], r[1]) for r in rows) == declared

    def test_nothing_has_gone_missing_its_seam_file(self, dep_buckets):
        """A capability whose seam names no `*.py` path cannot be classified;
        those are reported, not dropped. Empty today — `folder_sync` is the one
        concept seam and it declares no modules."""
        assert not dep_buckets["no_seam"], dep_buckets["no_seam"]

    def test_the_headline_counts_every_bucket(self, dep, dep_buckets,
                                              capsys, monkeypatch):
        """Checked against the actual output rather than the source: the two
        got out of step once already in the sibling checker, which is the only
        way this can go wrong."""
        monkeypatch.setattr(sys, "argv", ["capability_dependency.py"])
        assert dep.main() == 0
        head = capsys.readouterr().out.splitlines()[0]
        total = int(head.split()[0])
        n_used = int(head.split("·")[1].strip().split()[0])
        assert total == sum(len(dep_buckets[k])
                            for k in ("used", "indirect", "elsewhere",
                                      "probe", "no_seam"))
        assert n_used == len(dep_buckets["used"]), head
        assert n_used < total, "the used column cannot be the whole catalogue"


class TestUsedElsewhereOffTheSeamsPath:
    """The bucket the first draft lacked. A declared module can be genuinely
    used by real package code the DECLARED SEAM never reaches — calling that
    "probe only" is demonstrably false (the use exists) and calling it "used"
    is dishonest about what installing it buys (the seam never gets there)."""

    def test_use_in_an_unreachable_sibling_is_elsewhere_not_probe(
            self, dep, tmp_path):
        """The seam only probes; a sibling the seam never imports genuinely
        uses the dep. Neither "used" (not the seam) nor "probe" (the use is
        real) — the verdict must be the honest middle."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "import deadlib  # noqa: F401\n\n_FLAG = True\n",
            "pkg.store": "from deadlib import Engine\n\n\n"
                         "def build():\n    return Engine()\n",
        })
        bucket, why = dep._classify_module("deadlib", ["pkg.seam"], by_mod, {})
        assert bucket == "elsewhere", why
        assert "pkg.store" in why

    def test_the_vector_search_siblings_are_elsewhere_not_probe_only(
            self, dep, dep_buckets):
        """The live case: chromadb / lancedb / sqlite_vec back FULL store
        implementations (chroma_store.py, lance_store.py, vector_store.py)
        that the declared seam (ann_index.py) never reaches and nothing in
        production constructs. 'probe only — nothing anywhere uses it' was
        demonstrably false for them; the evidence must name the real user."""
        elsewhere = {(k, m): w for k, m, _s, w in dep_buckets["elsewhere"]}
        for entry, user in ((("vector_search", "chromadb"), "chroma_store"),
                            (("vector_search", "lancedb"), "lance_store"),
                            (("vector_search", "sqlite_vec"), "vector_store")):
            assert entry in elsewhere, (
                f"{entry} left the elsewhere bucket; buckets: "
                f"{ {k: len(v) for k, v in dep_buckets.items()} }")
            assert user in elsewhere[entry], elsewhere[entry]

    def test_probe_only_now_means_nothing_anywhere_by_construction(
            self, dep, dep_buckets):
        """The probe bucket's label — 'referenced by no code path anywhere in
        the package' — is only true because the elsewhere bucket exists. Pin
        it: no probe row may have a package module that uses the dep."""
        by_mod = dep._package_modules()
        cache: dict = {}
        for key, module, _seam, _why in dep_buckets["probe"]:
            users = dep._used_elsewhere_off_seam(module, by_mod, cache)
            assert not users, (
                f"({key}, {module}) is labelled probe-only but "
                f"{users} references it — it belongs in the elsewhere bucket")


class TestKnownLimitationsModuleGranularity:
    """These tests PIN THE CURRENT, LIMITED behaviour — each documents a shape
    the checker gets WRONG, so a future fix must retire the pin deliberately
    rather than silently change the verdict. The names say 'limitation'; the
    docstrings say what the truthful answer would be. Do not 'fix' these by
    editing the expected value to match a still-wrong checker."""

    def test_limitation_cross_function_use_is_laundered_to_indirect(
            self, dep, tmp_path):
        """TRUTH: probe-only. The seam's only call is helper.foo(); the dep is
        used only in helper.bar(), which nothing calls, so installing it
        changes nothing on any path the seam takes. The checker works at
        MODULE granularity ('the seam calls somewhere into helper, and helper
        uses the dep somewhere') and so reports indirect. A symbol-level call
        graph would be needed to say otherwise; that trade was considered and
        rejected, so the limitation is pinned instead."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "import deadlib  # noqa: F401\n"
                        "from . import helper\n\n\n"
                        "def go():\n    return helper.foo()\n",
            "pkg.helper": "from deadlib import Engine\n\n\n"
                          "def foo():\n    return 1\n\n\n"
                          "def bar():\n    return Engine()\n",
        })
        bucket, why = dep._classify_module("deadlib", ["pkg.seam"], by_mod, {})
        assert bucket == "indirect", (
            "LIMITATION PIN changed — if the checker now says 'probe' it "
            f"became symbol-aware; retire this pin. Got: {bucket} ({why})")

    def test_limitation_a_dead_code_reference_counts_as_a_call(
            self, dep, tmp_path):
        """TRUTH: probe-only. `if False: helper.foo()` never runs, but
        'references' is syntactic — any ast.Name load anywhere in the file
        counts, including unreachable code — so the dead reference launders
        the dep into indirect."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "import deadlib  # noqa: F401\n"
                        "from . import helper\n"
                        "if False:\n    helper.foo()\n",
            "pkg.helper": "from deadlib import Engine\n\n\n"
                          "def engine():\n    return Engine()\n",
        })
        bucket, why = dep._classify_module("deadlib", ["pkg.seam"], by_mod, {})
        assert bucket == "indirect", (
            "LIMITATION PIN changed — if the checker now says 'probe' it "
            f"learned reachability; retire this pin. Got: {bucket} ({why})")

    def test_limitation_a_shadowed_binding_counts_as_use(self, dep, tmp_path):
        """TRUTH: probe-only. Every load of `thing` resolves to the function
        PARAMETER, never to the import — the binding is a pure probe. The
        checker does no scope analysis, so the shadowed name reads as use."""
        by_mod = _by_mod(tmp_path, {
            "pkg.seam": "from deadlib import thing  # noqa: F401\n\n\n"
                        "def go(thing):\n    return thing\n",
        })
        bucket, why = dep._classify_module("deadlib", ["pkg.seam"], by_mod, {})
        assert bucket == "used", (
            "LIMITATION PIN changed — if the checker now says 'probe' it "
            f"grew scope analysis; retire this pin. Got: {bucket} ({why})")
