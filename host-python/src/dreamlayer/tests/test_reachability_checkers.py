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

    def test_the_known_gap_is_still_visible(self, hud):
        """15 of 24 declared cards have no Brain-side producer (was 18 before
        ObjectRecall, SavedMemory and JunoReply were wired). Every remaining
        one's producer lives in `orchestrator/ops_*.py`, which the shipped Brain
        never constructs (`decisions/0001`). This asserts the checker can still
        SEE that, not that the number is acceptable. As the gap closes this test
        should fail — read the number, fix the assertion, and keep it pointing
        at what is still open."""
        made = self._producers(hud)
        samples = hud._sample_builders()
        gap = [t for _, t, k in hud._declared_features()
               if not made.get(samples[k])]
        assert gap, ("every declared card now has a Brain-side producer — "
                     "excellent, and this assertion needs retiring")
        assert "Truth, checked live" in gap, (
            "fact_check gained a producer, or the scan stopped finding gaps")

    def test_the_cards_just_wired_are_out_of_the_gap(self, hud):
        """The other direction: closing three cards has to be visible too, or
        the checker is only ever reporting bad news and nobody will believe the
        good."""
        made = self._producers(hud)
        samples = hud._sample_builders()
        closed = {t for _, t, k in hud._declared_features() if made.get(samples[k])}
        for title in ("Where you left it", "Keep a moment", "Ask it anything"):
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
        assert live < device, (
            "the Live Lens is meant to be the SMALLER set — a handful of "
            "bespoke branches plus a generic fallback. If it caught up with "
            "halo-lua, check the scan is not matching comments again.")

    def test_the_generic_fallback_is_not_counted_as_a_drawing(self, hud):
        """`glassEventCard` draws `eyebrow` and `primary` only. Counting it
        would mark every card as rendered on a surface that silently drops the
        field carrying the answer."""
        live = hud._drawn_on_live_lens()
        assert "ReadyCard" not in live      # no branch; falls back, draws "…"
        assert "HarkCard" in live           # has a real branch

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
