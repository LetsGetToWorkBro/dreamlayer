"""test_halo_contrast_sweep.py — the on-glass palette gets its contrast sweep (#580).

The phone app has measured its theme pairings since #571
(`phone-app/src/__tests__/theme-contrast.test.ts`); the DEVICE palette —
`halo-lua/display/palette.lua`, the colors `renderer.lua` actually draws with —
had no equivalent, and `text_ghost` sat at 3.62:1 with nobody knowing whether
that was fine. This file is the sweep half of the issue. The policy half —
what floor the hint tier owes anybody — is the maintainer's call, not this
file's, so the ghost/dim tiers are MEASURED and classified here but no floor
is asserted on them (see NOT_ENFORCED). No palette value was changed to make
any of this pass; that was the explicit #571 rule ("changing the design to
make my own test pass") and it applies here twice over.

What the renderer draws on (read from the code, not assumed):

  * `frame.display.clear(0x000000)` — every frame composes over the palette's
    `background` token. Most text sits here.
  * `MAT.PANE` (`materials.lua`) — the Solid-material glass pane, a scanline
    disc/capsule in the `surface` token drawn behind card content. Text inside
    a pane sits on `surface`, which is slightly LIGHTER than `background`, so
    it is the stricter of the two backgrounds for any ink.

(The issue wondered about `paper`/`well` — those are phone-app Platinum
materials from #571; halo-lua has no such tokens. The two backgrounds above
are the whole story on the device.)

The floor enforced below is WCAG AA 4.5:1 for normal text — the floor #571
established for this product and the one the issue's own "comfortable" table
presupposes. The AA-large 3.0 tier is never reached for a different reason:
WCAG large text starts at 24px (or 18.66px bold) and the device's biggest
size is hero=22px (`typography.lua` DEVICE_FONT) — and the question is moot
anyway, since every enforced pairing clears 4.5.

Parser style follows the repo's existing Lua-reading tests
(`scripts/hud_reachability.py` read by test_reachability_checkers.py, and
test_brain_truth_read.py): strip Lua comments, regex the shapes the code
actually has, and pin the parser against known content so it cannot go
vacuous.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
PALETTE_LUA = ROOT / "halo-lua" / "display" / "palette.lua"
RENDERER_LUA = ROOT / "halo-lua" / "display" / "renderer.lua"
MATERIALS_LUA = ROOT / "halo-lua" / "display" / "materials.lua"
CARDS_PY = ROOT / "host-python" / "src" / "dreamlayer" / "hud" / "cards.py"

AA_NORMAL = 4.5  # WCAG AA, normal-size text — the floor #571 established

_LUA_COMMENT = re.compile(r"^\s*--.*$", re.MULTILINE)
# values may carry a trailing comment (`M.confidence_high = 0xB8FFE9  -- …`),
# which the whole-line comment stripper above deliberately leaves alone
_PALETTE_TOKEN = re.compile(r"^M\.([a-z_]+)\s*=\s*0x([0-9A-Fa-f]{6})\b",
                            re.MULTILINE)


def _lua(path: pathlib.Path) -> str:
    return _LUA_COMMENT.sub("", path.read_text(encoding="utf-8"))


def _palette() -> dict[str, int]:
    """Semantic tokens out of palette.lua: name -> 0xRRGGBB."""
    return {name: int(hexv, 16)
            for name, hexv in _PALETTE_TOKEN.findall(_lua(PALETTE_LUA))}


# ---------------------------------------------------------------------------
# The WCAG 2.x contrast maths, written out (no dependency to be wrong about)
# ---------------------------------------------------------------------------

def _channel(rgb: int, shift: int) -> float:
    v = ((rgb >> shift) & 0xFF) / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(rgb: int) -> float:
    return (0.2126 * _channel(rgb, 16) + 0.7152 * _channel(rgb, 8)
            + 0.0722 * _channel(rgb, 0))


def contrast(ink: int, bg: int) -> float:
    li, lb = _luminance(ink), _luminance(bg)
    hi, lo = max(li, lb), min(li, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------------------
# Reading the renderer: which ink is drawn as TEXT, and on which background
# ---------------------------------------------------------------------------

def _split_args(src: str, open_idx: int) -> list[str]:
    """Top-level comma split of the call whose `(` is at open_idx.

    Strings are skipped (a paren inside a literal must not change the depth);
    nested calls keep their parens. Raises rather than guessing on an
    unbalanced call — a parser that degrades silently reports a clean sweep.
    """
    args: list[str] = []
    depth = 0
    start = i = open_idx + 1
    while i < len(src):
        ch = src[i]
        if ch in "\"'":
            j = i + 1
            while j < len(src) and src[j] != ch:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                args.append(src[start:i].strip())
                return args
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(src[start:i].strip())
            start = i + 1
        i += 1
    raise AssertionError("unbalanced call in renderer.lua")


# text(str, x, y, COLOR, size) / text_block(str, x, y, COLOR, size, ...) carry
# the color at index 3; primitives.text_center(x, y, str, size, COLOR) at 4.
# `text` must not match `text_block`/`text_center`/PR-qualified calls.
_TEXT_CALLS = (
    (re.compile(r"(?<![\w.])text\s*\("), 3),
    (re.compile(r"(?<![\w.])text_block\s*\("), 3),
    (re.compile(r"text_center\s*\("), 4),
)
_P_TOKEN = re.compile(r"P\.([a-z_]+)\b")


def _text_color_exprs(src: str) -> list[str]:
    """The color argument of every text call in renderer.lua, in order."""
    found: list[tuple[int, str]] = []
    for pattern, color_idx in _TEXT_CALLS:
        for m in pattern.finditer(src):
            args = _split_args(src, src.index("(", m.start()))
            if len(args) > color_idx:
                found.append((m.start(), args[color_idx]))
    return [expr for _, expr in sorted(found)]


def _table_tokens(src: str, table: str) -> set[str]:
    """P.* tokens inside a `local NAME = { ... }` literal (FACT_COLOR etc.)."""
    m = re.search(table + r"\s*=\s*\{(.*?)\}", src, re.S)
    assert m, f"{table} table not found in renderer.lua"
    return set(_P_TOKEN.findall(m.group(1)))


def _local_def_tokens(src: str, var: str) -> set[str]:
    """P.* tokens on `local <var> = ...` lines — the values a variable-colored
    text call can actually draw in (`accent`, `dim`, `col`, ...)."""
    out: set[str] = set()
    for m in re.finditer(r"^\s*local\s+" + var + r"\s*=\s*(.+)$", src, re.M):
        out |= set(_P_TOKEN.findall(m.group(1)))
    return out


# ---------------------------------------------------------------------------
# The pairings — every ink x background the renderer draws as text.
#
# ENFORCED pairs clear AA_NORMAL and are asserted. The background for each was
# read off the draw functions: cards with a MAT.glass_disc/capsule pane put
# their content text on `surface`; cards without one (privacy class — "privacy
# cards get no pane", the ember set, the drift/scrub/deviation family) put it
# on `background`. Texts at a pane's edge are counted against the pane — the
# stricter reading.
# ---------------------------------------------------------------------------

ENFORCED: list[tuple[str, str, str]] = [
    # (where it is drawn, ink token, background token)
    # --- on `background` (no pane behind the text) ---
    ("SavedMemoryCard SAVED + primary; CommitmentRecall task; PersonContext why-line; "
     "CommitmentDrift/TimeScrub/DeviationAlert bodies; Ember primary rows; "
     "privacy layout rows", "text_primary", "background"),
    ("ObjectRecall bracketed detail; ProactiveMemory summary; PersonContext headline; "
     "LowConfidence 'Not sure'; privacy layout rows", "text_secondary", "background"),
    ("CommitmentRecall 'YOU PROMISED'; ProactiveMemory 'With <person>'; "
     "CommitmentDrift eyebrow/person; TimeScrubNode place", "memory_trace", "background"),
    ("GlanceChoice eyebrow (below the pane)", "accent_memory", "background"),
    ("SavedMemoryCard 'SAVED' (hero)", "accent_success", "background"),
    ("DeviationAlert 'SOUNDS DIFFERENT'", "warning_amber", "background"),
    ("PrivacyVeil 'PAUSED'; host-built privacy footers (cards.py)",
     "privacy_caution", "background"),
    ("host-built privacy eyebrows (cards.py ForgetLast/PrivateZone)",
     "privacy_danger", "background"),
    ("Ember 'EMBER' eyebrows; EmberFlare primary; EmberGraduated cue",
     "ember_glow", "background"),
    # --- on `surface` (behind a MAT.PANE glass pane/capsule) ---
    ("JunoReply/AnswerAhead/FactCheck/Hark/Scholar/Taste bodies; Message/Upcoming/"
     "Here/PersonDossier/SpokenCaption/MorningBrief primaries; TruthLens verdict "
     "capsule; GlanceChoice labels; non-privacy layout rows; fallback card title",
     "text_primary", "surface"),
    ("world_rows (Scholar/Taste/Message/MorningBrief); GlanceChoice scene; "
     "Message body; PersonDossier detail; non-privacy layout rows; fallback detail",
     "text_secondary", "surface"),
    ("ObjectRecall object label; CommitmentRecall due (glass capsule); "
     "PersonContext name", "memory_trace", "surface"),
    ("JunoReply 'JUNO'; AnswerAhead/Listening eyebrows; world_bed eyebrows",
     "accent_memory", "surface"),
    ("JunoReply 'JUNO' (action kind)", "accent_success", "surface"),
    ("FactCheck eyebrow (self_contradiction)", "accent_attention", "surface"),
    ("FactCheck eyebrow (disputed); Hark 'LISTEN' (urgent); Upcoming eyebrow/detail "
     "(<= 5 min)", "warning_amber", "surface"),
]

# MEASURED, NOT ENFORCED. Each of these is a de-emphasis tier — the hint ink
# itself or a `_dim` twin carrying a cooled detail row — so the floor it owes
# is the policy decision #580 explicitly reserves for the maintainer ("State a
# floor for the hint tier and write the reasoning next to it, whatever you
# decide"). This file's job is that the numbers below exist and stay
# classified; his job is the floor. Several are under even the AA-large 3.0
# line — that is a measurement, reported, not a verdict.
NOT_ENFORCED: list[tuple[str, str]] = [
    ("text_ghost",
     "the hint tier #580 is about: 3.62 on background, 3.21 on surface — under "
     "AA 4.5, over AA-large 3.0. Whether the HUD's ghost ink owes 4.5, 3.0, or "
     "a device-specific number is the maintainer's stated decision, not this "
     "file's. Note it also carries whole card messages (ErrorCard primary, "
     "'Connect a Brain', 'Try rephrasing'), not only footers."),
    ("text_ghost_static",
     "the one-LSB ghost twin (3.62/3.20): FactCheck 'unverified' eyebrow and "
     "the Scholar/Taste 'connect a Brain' state. Same tier, same open floor."),
    ("accent_memory_dim",
     "the cooled memory-teal twin (4.00/3.54): AnswerAhead question line, "
     "Message 'tap to reply', Here/Taste/PersonDossier detail rows, Hark "
     "(non-urgent) detail. A deliberate second-rank tier."),
    ("accent_success_dim",
     "3.97/3.51: FactCheck detail when the verdict is 'supported' — i.e. the "
     "basis text of a fact-check draws in the dim twin."),
    ("warning_amber_dim",
     "2.69 on background, 2.38 on surface — under even 3.0: FactCheck detail "
     "when 'disputed', Hark detail when urgent."),
    ("accent_attention_dim",
     "2.47 on background, 2.18 on surface — under even 3.0: FactCheck detail "
     "when 'self_contradiction', and every vetoed row in the Taste/Scholar "
     "lists (world_rows)."),
    ("ember_glow_dim",
     "3.70/3.28: the EmberReveal cue — deliberately the dimmest ember moment "
     "('forgetting stays kind')."),
    ("border_subtle",
     "1.83/1.62 — under even 3.0: the FactCheck detail fallback when the "
     "verdict names no FACT_DIM entry (and FACT_DIM['unverified']). Mostly a "
     "geometry token; these two text uses ride on it."),
]

# Drawn by renderer.lua but never as text (dots, jewels, rings, ramps, blooms).
# Declared so the partition below is a classification, not a misc bucket.
GEOMETRY_ONLY = {"accent_memory_static", "confidence_low", "confidence_med",
                 "confidence_high"}

# Defined in palette.lua and referenced by NOTHING in renderer.lua. Said out
# loud rather than held to a floor — the #571 ink3 reasoning: asserting a
# floor on a token nothing draws would be asserting about nothing.
UNRENDERED = {"accent_error", "memory_rail", "status_paused"}

BACKGROUNDS = {"background", "surface"}

# The variable color expressions renderer.lua's text calls may use, and why
# each is safe: the test derives their possible tokens from the source and
# requires them all classified. A NEW variable-colored text call fails here
# until its origins are pinned — the sweep cannot quietly stop seeing one.
KNOWN_VARIABLE_EXPRS = {"color", "dim", "accent", "col",
                        "spec.color or fallback_color"}


@pytest.fixture(scope="module")
def palette() -> dict[str, int]:
    if not PALETTE_LUA.exists():
        pytest.skip("halo-lua not in this checkout")
    return _palette()


@pytest.fixture(scope="module")
def renderer_src() -> str:
    if not RENDERER_LUA.exists():
        pytest.skip("halo-lua not in this checkout")
    return _lua(RENDERER_LUA)


def _enforced_inks() -> set[str]:
    return {ink for _, ink, _ in ENFORCED}


def _not_enforced_inks() -> set[str]:
    return {ink for ink, _ in NOT_ENFORCED}


class TestTheMathsItself:
    """If the ratio helper is wrong, every assertion below it is vacuously
    true — so the helper is pinned before the palette is (#571's first rule)."""

    def test_the_known_extremes(self):
        assert contrast(0xFFFFFF, 0x000000) == pytest.approx(21.0, abs=1e-9)
        assert contrast(0x000000, 0xFFFFFF) == pytest.approx(21.0, abs=1e-9)
        assert contrast(0xFFFFFF, 0xFFFFFF) == pytest.approx(1.0, abs=1e-9)

    def test_the_wcag_boundary_greys(self):
        """The worked pair every WCAG 1.4.3 walkthrough lands on: #767676 is
        the darkest grey that JUST fails 4.5 on white, #777777's twin just
        under it — pinned to 2dp so a knee/gamma slip in _channel shows here."""
        assert contrast(0x767676, 0xFFFFFF) == pytest.approx(4.54, abs=0.005)
        assert contrast(0x777777, 0xFFFFFF) == pytest.approx(4.48, abs=0.005)

    def test_reproduces_the_565_pair(self):
        """#571's fixture pair, kept so the two sweeps agree on the maths."""
        assert contrast(0x9FA6AA, 0x3E4044) == pytest.approx(4.21, abs=0.005)
        assert contrast(0x9FA6AA, 0x3E4044) < AA_NORMAL

    def test_reproduces_the_issue_580_hand_computed_table(self):
        """The six ratios the issue author ran by hand (literal hexes, so this
        pins the MATHS against his independent arithmetic and keeps pinning it
        even if the palette later moves)."""
        expected = {
            (0xECF0F1, 0x000000): 18.30,   # text_primary on background
            (0xA8B8C0, 0x000000): 10.28,   # text_secondary on background
            (0x00FFAA, 0x000000): 15.88,   # confidence_med on background
            (0x56D364, 0x000000): 10.90,   # accent_success on background
            (0xE06B52, 0x000000): 6.39,    # accent_attention on background
            (0x58686F, 0x000000): 3.62,    # text_ghost on background
        }
        for (ink, bg), ratio in expected.items():
            assert contrast(ink, bg) == pytest.approx(ratio, abs=0.005), (
                f"#{ink:06X} on #{bg:06X}: expected ~{ratio}, "
                f"got {contrast(ink, bg):.4f}")

    def test_is_symmetric(self):
        assert contrast(0x58686F, 0x000000) == pytest.approx(
            contrast(0x000000, 0x58686F), abs=1e-12)


class TestTheSurfacesAreWhatTheSweepThinks:
    """The two-background model, pinned to the code rather than assumed."""

    def test_the_parser_sees_the_palette(self, palette):
        """Non-vacuity: a parser that found nothing would pass every floor."""
        assert len(palette) >= 25, f"only {len(palette)} tokens parsed"
        assert palette["background"] == 0x000000
        assert palette["text_ghost"] == 0x58686F

    def test_frames_clear_to_the_background_token(self, renderer_src, palette):
        clears = {int(m, 16) for m in
                  re.findall(r"frame\.display\.clear\(0x([0-9A-Fa-f]{6})\)",
                             renderer_src)}
        assert clears == {palette["background"]}, (
            f"frames clear to {clears}, not the background token — the sweep's "
            "base background is wrong")

    def test_the_pane_is_the_surface_token(self, palette):
        src = _lua(MATERIALS_LUA)
        m = re.search(r"^M\.PANE\s*=\s*P\.([a-z_]+)", src, re.M)
        assert m and m.group(1) == "surface", (
            "MAT.PANE no longer draws in P.surface — the second background in "
            "this sweep is stale")
        assert "surface" in palette

    def test_surface_is_the_stricter_background(self, palette):
        """Why edge-of-pane texts are counted against the pane: surface is the
        LIGHTER background, so it gives the lower ratio for every ink."""
        for _, ink, _ in ENFORCED:
            assert contrast(palette[ink], palette["surface"]) < \
                   contrast(palette[ink], palette["background"]), ink


class TestTheSweep:
    """Every enforced pairing clears AA 4.5 — the floor #571 established and
    the issue's 'comfortable' table presupposes. Failure messages carry the
    numbers so a regression says WHAT moved."""

    @pytest.mark.parametrize(
        "where,ink,bg", ENFORCED, ids=[f"{i}-on-{b}" for _, i, b in ENFORCED])
    def test_pairing_clears_aa_normal(self, palette, where, ink, bg):
        ratio = contrast(palette[ink], palette[bg])
        assert ratio >= AA_NORMAL, (
            f"{ink} on {bg} is {ratio:.2f}:1, below the {AA_NORMAL}:1 floor\n"
            f"  drawn: {where}\n"
            f"  ink #{palette[ink]:06X} on #{palette[bg]:06X}")


class TestTheHintTierIsMeasuredNotJudged:
    """The #571 ink3 move, applied to the whole de-emphasis family: no floor
    is asserted on tiers whose floor is the maintainer's open decision — but
    the hierarchy that gives those tiers their meaning IS pinned, and every
    entry carries its reasoning."""

    def test_every_not_enforced_entry_states_its_reason(self):
        """An empty reason turns the bucket into a place to hide gaps — the
        by_design rule from the capability checker, applied here."""
        for ink, why in NOT_ENFORCED:
            assert ink and len(why) > 40, (ink, why)

    def test_the_text_hierarchy_holds_on_both_backgrounds(self, palette):
        """The cheap way to 'fix' ghost contrast is to lift it toward
        secondary, which fixes the number and destroys the hierarchy (#571's
        ordering check, verbatim in spirit)."""
        for bg in ("background", "surface"):
            ghost = contrast(palette["text_ghost"], palette[bg])
            secondary = contrast(palette["text_secondary"], palette[bg])
            primary = contrast(palette["text_primary"], palette[bg])
            assert ghost < secondary < primary, (
                f"on {bg}: ghost {ghost:.2f}, secondary {secondary:.2f}, "
                f"primary {primary:.2f}")

    def test_the_dim_twins_stay_below_their_bright_twins(self, palette):
        """'dim' is a promise about ordering, whatever floor the tier gets."""
        for bright, dim in (("accent_memory", "accent_memory_dim"),
                            ("accent_success", "accent_success_dim"),
                            ("accent_attention", "accent_attention_dim"),
                            ("warning_amber", "warning_amber_dim"),
                            ("ember_glow", "ember_glow_dim")):
            for bg in ("background", "surface"):
                assert contrast(palette[dim], palette[bg]) < \
                       contrast(palette[bright], palette[bg]), (bright, dim, bg)


class TestTheSweepCannotGoStale:
    """Completeness, in both directions: every palette token is classified
    exactly once, and every ink the renderer draws as text is in the sweep.
    A new text color, a new token, or a token that stops being drawn fails
    here until someone classifies it — the reachability checkers' rule."""

    def _text_tokens(self, renderer_src: str) -> set[str]:
        """Every token that reaches a text call, however indirect."""
        tokens: set[str] = set()
        variables: set[str] = set()
        for expr in _text_color_exprs(renderer_src):
            found = set(_P_TOKEN.findall(expr))
            if found:
                tokens |= found
            else:
                variables.add(expr)
        assert variables <= KNOWN_VARIABLE_EXPRS, (
            f"a text call draws in an unclassified expression: "
            f"{sorted(variables - KNOWN_VARIABLE_EXPRS)} — pin its possible "
            "tokens here so the sweep keeps seeing it")
        # the values those variables can actually hold
        tokens |= _table_tokens(renderer_src, "FACT_COLOR")
        tokens |= _table_tokens(renderer_src, "FACT_DIM")
        for var in ("color", "dim", "accent", "col"):
            tokens |= _local_def_tokens(renderer_src, var)
        # the layout-row fallbacks: row("eyebrow", ..., P.text_secondary, ...)
        for m in re.finditer(r"(?<![\w.])row\s*\(", renderer_src):
            args = _split_args(renderer_src,
                               renderer_src.index("(", m.start()))
            if len(args) > 3:
                tokens |= set(_P_TOKEN.findall(args[3]))
        return tokens

    def _host_layout_tokens(self) -> set[str]:
        """Inks the HOST sends into draw_layout_card rows (cards.py builds the
        layout payloads; renderer.lua draws spec.color verbatim). Same palette
        — themes.py mirrors palette.lua — so the same ratios apply."""
        if not CARDS_PY.exists():
            pytest.skip("host-python not in this checkout")
        src = CARDS_PY.read_text(encoding="utf-8")
        rows = re.findall(
            r'"(eyebrow|primary|detail|footer)"\s*:\s*\{[^{}]*?"color"\s*:\s*T\.(\w+)',
            src)
        assert len(rows) >= 5, f"only {len(rows)} layout text rows parsed"
        return {token.lower() for _, token in rows}

    def test_every_palette_token_is_classified_exactly_once(self, palette):
        inks = _enforced_inks() | _not_enforced_inks()
        buckets = [BACKGROUNDS, inks, GEOMETRY_ONLY, UNRENDERED]
        for i, a in enumerate(buckets):
            for b in buckets[i + 1:]:
                assert not (a & b), f"token in two buckets: {a & b}"
        classified = set().union(*buckets)
        assert classified == set(palette), (
            f"unclassified: {set(palette) - classified}; "
            f"classified but not in palette: {classified - set(palette)}")

    def test_every_text_ink_is_in_the_sweep(self, renderer_src, palette):
        drawn = self._text_tokens(renderer_src) | self._host_layout_tokens()
        unknown = drawn - set(palette)
        assert not unknown, f"renderer draws tokens palette.lua lacks: {unknown}"
        unclassified = drawn - _enforced_inks() - _not_enforced_inks()
        assert not unclassified, (
            f"drawn as text but in no pairing table: {sorted(unclassified)}")

    def test_every_classified_ink_is_actually_drawn_as_text(self, renderer_src):
        """The other direction — a pairing for a token nothing draws as text
        would be asserting about nothing (#571's ink3 reasoning)."""
        drawn = self._text_tokens(renderer_src) | self._host_layout_tokens()
        phantom = (_enforced_inks() | _not_enforced_inks()) - drawn
        assert not phantom, (
            f"classified as text ink but nothing draws it as text: "
            f"{sorted(phantom)}")

    def test_geometry_only_tokens_never_reach_a_text_call(self, renderer_src):
        drawn = self._text_tokens(renderer_src) | self._host_layout_tokens()
        leaked = GEOMETRY_ONLY & drawn
        assert not leaked, (
            f"geometry token now drawn as text — classify its pairing: "
            f"{sorted(leaked)}")

    def test_the_unrendered_set_is_exact(self, renderer_src, palette):
        """Unrendered is a claim about the code, so it is pinned rather than
        assumed — and it cannot silently grow: every other token must be
        referenced by the renderer (surface via materials.M.PANE, pinned in
        TestTheSurfacesAreWhatTheSweepThinks)."""
        referenced = {t for t in palette
                      if re.search(r"P\." + t + r"\b", renderer_src)}
        unrendered = (set(palette) - referenced) - {"surface"}
        assert unrendered == UNRENDERED, (
            f"tokens nothing renders changed: now {sorted(unrendered)}")
