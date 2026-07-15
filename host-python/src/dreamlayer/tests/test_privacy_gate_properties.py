"""Property-based revert net for the privacy gate — the product's core safety
contract (audit 2026-07-14 Section 7, "Test Infrastructure Quality").

The privacy gate has two independent veils (an explicit *pause* and the
*incognito* session shield) that gate two operations (*capture* = keep what we
perceive now; *recall* = read back what we already know). The contract, stated
as one truth table:

    capture is blocked by EITHER veil   →  allow_capture() == not (paused or incognito)
    recall  is blocked ONLY by a pause  →  allow_recall()  == not paused

These properties pin that table over ALL state combinations and over ANY
transition sequence, so a mutation that flips the OR to an AND, or that makes
incognito block recall, MUST fail at least one of them. The API here is derived
from dreamlayer/memory/privacy.py — no invented methods.

Run standalone (does not touch the rest of the suite):
    python -m pytest tests/test_privacy_gate_properties.py -q -p no:cacheprovider
"""
from __future__ import annotations

import itertools

from hypothesis import given, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from dreamlayer.memory.privacy import (
    AlwaysOnGate,
    NullGate,
    PrivacyGate,
    requires_capture,
    requires_recall,
)

BOOLS = (False, True)


def _gate_in_state(paused: bool, incognito: bool) -> PrivacyGate:
    """Build a PrivacyGate in an exact (paused, incognito) state using only the
    real public API (pause/resume + set_incognito)."""
    g = PrivacyGate()
    if paused:
        g.pause()
    g.set_incognito(incognito)
    return g


# ---------------------------------------------------------------------------
# 1. The truth table, exhaustively over every (paused, incognito) in {T,F}^2.
#    A plain loop guarantees all four combinations are checked on every run
#    (not left to Hypothesis' example budget) — this is the primary revert net.
# ---------------------------------------------------------------------------
def test_truth_table_exhaustive_over_all_state_combos():
    for paused, incognito in itertools.product(BOOLS, BOOLS):
        g = _gate_in_state(paused, incognito)
        why = f"(paused={paused}, incognito={incognito})"
        # capture: blocked whenever paused OR incognito
        assert g.allow_capture() == (not (paused or incognito)), why
        # recall: blocked IFF paused; incognito ALONE must not block it
        assert g.allow_recall() == (not paused), why
        # the observable `paused` property tracks the pause veil exactly
        assert g.paused == paused, why


@given(st.booleans(), st.booleans())
def test_truth_table_property(paused, incognito):
    """Same contract, driven by Hypothesis, so any future widening of the state
    space is exercised too."""
    g = _gate_in_state(paused, incognito)
    assert g.allow_capture() == (not (paused or incognito))
    assert g.allow_recall() == (not paused)


def test_fresh_gate_allows_both():
    """A freshly constructed gate (no pause, no incognito) permits everything —
    pins the __init__ defaults so a False->True mutant on either flag dies."""
    g = PrivacyGate()
    assert g.allow_capture() is True
    assert g.allow_recall() is True
    assert g.paused is False


# ---------------------------------------------------------------------------
# 2. The two load-bearing asymmetries, isolated so the exact mutant that would
#    erase each one has a dedicated killer.
# ---------------------------------------------------------------------------
@given(st.booleans())
def test_incognito_alone_never_blocks_recall(incognito):
    """Incognito stops *keeping* new memories, never *recalling* old ones. A
    mutant that makes allow_recall consult incognito fails here."""
    g = _gate_in_state(paused=False, incognito=incognito)
    assert g.allow_recall() is True
    # ...and capture still reflects incognito
    assert g.allow_capture() == (not incognito)


@given(st.booleans())
def test_pause_blocks_both_regardless_of_incognito(incognito):
    """A full pause is 'deaf and blind': both capture and recall are off, no
    matter the incognito flag."""
    g = _gate_in_state(paused=True, incognito=incognito)
    assert g.allow_capture() is False
    assert g.allow_recall() is False


# ---------------------------------------------------------------------------
# 3. The two constant gates: NullGate fails CLOSED, AlwaysOnGate fails OPEN.
#    Both are stateless, so "always" is the whole contract.
# ---------------------------------------------------------------------------
def test_null_gate_always_denies_both():
    g = NullGate()
    assert g.allow_capture() is False
    assert g.allow_recall() is False


def test_always_on_gate_always_allows_both():
    g = AlwaysOnGate()
    assert g.allow_capture() is True
    assert g.allow_recall() is True


# ---------------------------------------------------------------------------
# 4. Transition algebra: idempotence, independence, and order-invariance.
#    The two veils are separate flags precisely so one can never silently clear
#    the other — pin that so a refactor that couples them is caught.
# ---------------------------------------------------------------------------
@given(st.booleans(), st.booleans())
def test_pause_is_idempotent(paused, incognito):
    g = _gate_in_state(paused, incognito)
    g.pause()
    once = (g.allow_capture(), g.allow_recall(), g.paused)
    g.pause()
    assert (g.allow_capture(), g.allow_recall(), g.paused) == once
    assert once == (False, False, True)


@given(st.booleans(), st.booleans())
def test_resume_is_idempotent(paused, incognito):
    g = _gate_in_state(paused, incognito)
    g.resume()
    once = (g.allow_recall(), g.paused)
    g.resume()
    assert (g.allow_recall(), g.paused) == once
    assert g.paused is False


@given(st.booleans())
def test_set_incognito_is_idempotent(on):
    g = PrivacyGate()
    g.set_incognito(on)
    once = g.allow_capture()
    g.set_incognito(on)
    assert g.allow_capture() == once
    assert g.allow_capture() == (not on)


def test_resume_does_not_clear_incognito():
    """Lifting the pause must NOT silently exit incognito — capture stays off."""
    g = PrivacyGate()
    g.pause()
    g.set_incognito(True)
    g.resume()
    assert g.paused is False
    assert g.allow_capture() is False   # incognito still shields capture
    assert g.allow_recall() is True     # pause lifted -> recall returns


def test_exit_incognito_does_not_clear_pause():
    """Exiting incognito must NOT silently lift the pause — both stay off."""
    g = PrivacyGate()
    g.pause()
    g.set_incognito(True)
    g.set_incognito(False)
    assert g.paused is True
    assert g.allow_capture() is False
    assert g.allow_recall() is False


@given(st.booleans(), st.booleans())
def test_veils_commute(paused, incognito):
    """Applying the pause and incognito veils in either order yields the same
    gate posture — they are genuinely independent inputs."""
    g_pause_first = PrivacyGate()
    if paused:
        g_pause_first.pause()
    g_pause_first.set_incognito(incognito)

    g_incog_first = PrivacyGate()
    g_incog_first.set_incognito(incognito)
    if paused:
        g_incog_first.pause()

    assert (g_pause_first.allow_capture(), g_pause_first.allow_recall()) == (
        g_incog_first.allow_capture(),
        g_incog_first.allow_recall(),
    )


@given(st.sampled_from([0, 1, 2, "", "x", None, [], [1], 0.0, 3.5]))
def test_set_incognito_coerces_by_truthiness(val):
    """set_incognito(bool(on)) — a non-bool argument gates by its truthiness."""
    g = PrivacyGate()
    g.set_incognito(val)
    assert g.allow_capture() == (not bool(val))
    assert g.allow_recall() is True     # incognito never touches recall


# ---------------------------------------------------------------------------
# 5. Stateful fuzz: after ANY sequence of pause / resume / enter / exit, the
#    two-veil contract still holds. This is the broadest revert net — a shadow
#    model tracks the intended state and the invariant re-derives the table.
# ---------------------------------------------------------------------------
class PrivacyGateStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.gate = PrivacyGate()
        self.paused = False
        self.incognito = False

    @rule()
    def do_pause(self):
        self.gate.pause()
        self.paused = True

    @rule()
    def do_resume(self):
        self.gate.resume()
        self.paused = False

    @rule()
    def enter_incognito(self):
        self.gate.set_incognito(True)
        self.incognito = True

    @rule()
    def exit_incognito(self):
        self.gate.set_incognito(False)
        self.incognito = False

    @invariant()
    def two_veil_contract_holds(self):
        assert self.gate.allow_capture() == (not (self.paused or self.incognito))
        assert self.gate.allow_recall() == (not self.paused)
        assert self.gate.paused == self.paused


TestPrivacyGateStateMachine = PrivacyGateStateMachine.TestCase
TestPrivacyGateStateMachine.settings = settings(max_examples=200, deadline=None)


# ---------------------------------------------------------------------------
# 6. The gate's call-site helpers (@requires_capture / @requires_recall) are the
#    ~18 hand-written guards collapsed into one idiom. Their contract:
#      * a decorated capture method returns None IFF allow_capture() is False;
#      * a decorated recall method returns None IFF allow_recall() is False;
#      * the gate resolves from self._privacy OR self.privacy;
#      * a MISSING gate fails CLOSED (deny both) — the 2026-07-15 footgun-closer.
# ---------------------------------------------------------------------------
def _lens_with_gate(gate, attr="_privacy"):
    class Lens:
        def keep(self):
            return "kept"

        def read(self):
            return "read"

    # decorate here so both the underscore and non-underscore attribute names
    # exercise the same wrapper's gate-resolution path.
    Lens.keep = requires_capture(Lens.keep)
    Lens.read = requires_recall(Lens.read)
    lens = Lens()
    setattr(lens, attr, gate)
    return lens


@given(st.booleans(), st.booleans())
def test_decorators_mirror_the_gate(paused, incognito):
    lens = _lens_with_gate(_gate_in_state(paused, incognito))
    assert (lens.keep() is not None) == (not (paused or incognito))
    assert (lens.read() is not None) == (not paused)


def test_decorators_resolve_via_privacy_attribute_fallback():
    """Gate wired as self.privacy (no underscore) resolves too — pins the second
    getattr so a mutant to its "privacy" attribute name is caught."""
    lens = _lens_with_gate(AlwaysOnGate(), attr="privacy")
    assert lens.keep() == "kept"
    assert lens.read() == "read"

    denied = _lens_with_gate(NullGate(), attr="privacy")
    assert denied.keep() is None
    assert denied.read() is None


def test_decorators_fail_closed_when_no_gate_is_wired():
    class Lens:
        @requires_capture
        def keep(self):
            return "kept"

        @requires_recall
        def read(self):
            return "read"

    lens = Lens()
    assert lens.keep() is None      # missing gate -> deny (was: allow, pre-2026-07-15)
    assert lens.read() is None


def test_decorators_incognito_blocks_capture_but_not_recall():
    g = PrivacyGate()
    g.set_incognito(True)
    lens = _lens_with_gate(g)
    assert lens.keep() is None      # incognito stops keeping
    assert lens.read() == "read"    # ...but recall still works
