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


class TestTheGlassIsTheONETheBrainCanReach:
    """The correction that mattered most, and the one a green checker hid.

    An earlier draft asked only "does `halo-lua` draw this type" and answered
    yes for all 24. But `Brain.push_event` fans out to the LIVE LENS — an SSE
    stream to the browser page in `live.py` — and nothing under `ai_brain/`
    calls `bridge.send_card`, so no Brain push has any path to the glasses
    firmware at all. The checker was measuring the Orchestrator's renderer to
    decide whether the Brain's cards were visible.
    """

    def test_the_brain_has_no_path_to_the_device_renderer(self):
        import pathlib
        import subprocess
        root = pathlib.Path(__file__).resolve().parents[4]
        hits = subprocess.run(
            ["grep", "-rn", "send_card", str(root / "host-python/src/dreamlayer/ai_brain")],
            capture_output=True, text=True).stdout.strip()
        assert not hits, (
            "something under ai_brain/ now calls send_card — if the Brain has "
            f"gained a path to halo-lua, this whole model needs revisiting:\n{hits}")

    def test_the_two_renderers_are_measured_separately(self, hud):
        device = hud._drawn_on_glass()
        live = hud._drawn_on_live_lens()
        assert device and live
        assert len(live) < len(device), (
            "the Live Lens is meant to be the SMALLER set — bespoke branches "
            "for what the Brain pushes, plus a generic fallback. If it caught "
            "up with halo-lua, check the scan is not matching comments again.")
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
        assert brain_only, (
            "no Brain-only card types at all — ConsistencyCard, StasisCard and "
            "QuestRewardCard are pushed by lens_hosts and drawn by no device "
            "renderer, so at least those three are expected here.")
        for ctype in brain_only:
            assert ctype in pushed or ctype in hud._BRAIN_ONLY_PUSHED, (
                f"{ctype} has a Live Lens branch but nothing pushes it — "
                "either wire the push or drop the branch.")

    def test_the_generic_fallback_is_not_counted_as_a_drawing(self, hud):
        """`glassEventCard` draws `eyebrow` and `primary` only. Counting it
        would mark every card as rendered on a surface that silently drops the
        field carrying the answer."""
        live = hud._drawn_on_live_lens()
        assert "HarkCard" in live           # has a real branch
        # The negative case used to be ReadyCard, which now HAS a branch — it is
        # `{type, dismiss_ms}` and nothing else, so the fallback drew its "…"
        # placeholder, i.e. a resting state that looked like a failure.
        # ErrorCard takes its place: still no branch, still must not be counted.
        assert "ErrorCard" not in live
        # …and the scan must not have degenerated into "any name in the file".
        # These appear in comments and payloads here but have no dispatch arm.
        assert "PaletteShiftCard" not in live
        assert "QueryListeningCard" not in live

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
        """74 today. The count matters because the handoff said ~39 for months
        — a checker reading half the catalogue would have agreed with it."""
        decl = caps._declared_caps()
        assert len(decl) >= 70, f"only {len(decl)} capabilities parsed"

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

    def test_orchestrator_seams_land_in_by_design_not_in_the_open_list(self, caps):
        assert caps._by_design("orchestrator/wakeword.py")
        assert not caps._by_design("memory/doc_schema.py")

    def test_the_dormant_set_is_read_from_capabilities_not_hardcoded(self, caps):
        """`_NOT_WIRED` is the product's own honest-status list. Reading it is
        what stopped the OPEN bucket printing 19 capabilities as "no reason on
        file" when 18 of them are named there with the reason written out."""
        dormant = caps._declared_dormant()
        assert len(dormant) >= 15, f"only {len(dormant)} parsed — set literal?"
        for key in ("memory_dedup", "social_graph", "live_interpret"):
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
        # inert bucket and hide the real shortlist
        assert "coreml_ondevice" not in promoted
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
                 "dormant", "expected", "concepts")
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
        """Two real pushes defeat a one-hop resolver. They are listed, not
        dropped — and each must still be a type something actually builds."""
        assert hud._BRAIN_ONLY_PUSHED
        inline = hud._inline_card_types(self._reachable(hud))
        for ctype in hud._BRAIN_ONLY_PUSHED:
            assert ctype in inline, f"{ctype} is declared pushed but unbuilt"


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
