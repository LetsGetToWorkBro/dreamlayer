"""Boundary unit tests for the safety contracts (v2/contracts.py).

CrossHair (test_contracts_crosshair.py) proves the ∀-properties hold, but a
proof of "the postcondition holds" doesn't pin the *exact* behavior at the
boundaries — and under a mutation tester CrossHair is blind anyway (mutmut
swaps the function body behind a dispatcher that CrossHair's source
introspection can't see). So these example-based tests nail down the precise
edge behavior: spend at exactly one token, each counter op, the accept-slot
truth table, refill direction and saturation. They are written to be
mutation-adequate — flip an operator, a boundary, or a constant in contracts.py
and one of these fails. Together with the proofs they are belt and suspenders.
"""
from dreamlayer.reality_compiler.v2 import contracts


class TestSaturate:
    def test_inc_adds_then_clamps(self):
        assert contracts.saturate(0, "inc", 5, 0, 10) == 5
        assert contracts.saturate(8, "inc", 5, 0, 10) == 10        # clamps at hi

    def test_dec_subtracts_then_clamps(self):
        assert contracts.saturate(5, "dec", 2, 0, 10) == 3
        assert contracts.saturate(1, "dec", 5, 0, 10) == 0         # clamps at lo

    def test_set_replaces_then_clamps(self):
        assert contracts.saturate(9, "set", 4, 0, 10) == 4
        assert contracts.saturate(0, "set", 99, 0, 10) == 10       # clamps at hi
        assert contracts.saturate(0, "set", -99, 0, 10) == 0       # clamps at lo

    def test_ops_are_distinct(self):
        # inc/dec/set on the same inputs must all differ — kills a mutant that
        # confuses the op dispatch (== -> !=, or a swapped branch)
        assert contracts.saturate(5, "inc", 3, 0, 100) == 8
        assert contracts.saturate(5, "dec", 3, 0, 100) == 2
        assert contracts.saturate(5, "set", 3, 0, 100) == 3

    def test_result_never_leaves_bounds(self):
        for op, amt in (("inc", 1000), ("dec", 1000), ("set", 1000),
                        ("set", -1000)):
            r = contracts.saturate(5, op, amt, 2, 7)
            assert 2 <= r <= 7


class TestSpendToken:
    def test_spends_at_exactly_one(self):
        # the boundary that matters: exactly one token is spendable
        spent, after = contracts.spend_token(1.0)
        assert spent is True and after == 0.0

    def test_just_below_one_cannot_spend(self):
        spent, after = contracts.spend_token(0.999)
        assert spent is False and after == 0.999

    def test_empty_bucket_cannot_spend(self):
        spent, after = contracts.spend_token(0.0)
        assert spent is False and after == 0.0

    def test_spending_removes_exactly_one(self):
        spent, after = contracts.spend_token(2.5)
        assert spent is True and after == 1.5           # not 0, not 2.5

    def test_flag_matches_availability(self):
        assert contracts.spend_token(3.0)[0] is True
        assert contracts.spend_token(0.5)[0] is False


class TestRefillTokens:
    def test_adds_over_time(self):
        # + direction, below burst so min() doesn't mask it: kills the sign flip
        assert contracts.refill_tokens(0.0, 1.0, 1.0, 5.0) == 1.0
        assert contracts.refill_tokens(1.0, 2.0, 1.5, 100.0) == 4.0

    def test_never_exceeds_burst(self):
        assert contracts.refill_tokens(4.0, 10.0, 10.0, 5.0) == 5.0   # capped

    def test_zero_elapsed_is_a_noop(self):
        assert contracts.refill_tokens(2.0, 0.0, 5.0, 5.0) == 2.0

    def test_never_loses_tokens(self):
        assert contracts.refill_tokens(3.0, 0.5, 1.0, 5.0) >= 3.0


class TestClampText:
    def test_clamps_to_max(self):
        assert contracts.clamp_text("abcdef", 3) == "abc"

    def test_short_string_untouched(self):
        assert contracts.clamp_text("hi", 10) == "hi"

    def test_zero_max_yields_empty(self):
        assert contracts.clamp_text("anything", 0) == ""

    def test_exact_length_untouched(self):
        assert contracts.clamp_text("abc", 3) == "abc"

    # -- the canonical unit is UTF-8 BYTES, cut on a codepoint boundary (P2-12).
    # These non-ASCII pairs are the mutant-killers for the boundary walk: each
    # pins the continuation-byte test (& 0xC0 == 0x80) and the backward step
    # (n -= 1) with a cut that lands mid-sequence, where any mutation either
    # returns too many bytes or splits a codepoint (decode error).

    def test_two_byte_char_cut_mid_sequence_drops_the_char(self):
        # "é" is C3 A9; max_len=1 lands on the continuation byte → back off to ""
        assert contracts.clamp_text("é", 1) == ""

    def test_three_byte_chars_cut_on_and_off_boundary(self):
        # "日本語" is 3 bytes per char: 3 keeps exactly one, 4 must NOT split 本
        assert contracts.clamp_text("日本語", 3) == "日"
        assert contracts.clamp_text("日本語", 4) == "日"
        assert contracts.clamp_text("日本語", 6) == "日本"

    def test_four_byte_emoji_kept_whole_or_dropped_whole(self):
        assert contracts.clamp_text("😀", 3) == ""       # can't fit 4 bytes in 3
        assert contracts.clamp_text("😀", 4) == "😀"

    def test_result_never_exceeds_max_bytes_and_stays_valid_utf8(self):
        # kills the walk-direction mutants (n += 1 walks past the cut) and any
        # relaxed comparison: the kept prefix must fit AND round-trip cleanly
        for s in ("héllo wörld", "日本語のテキスト", "a😀b日c", "café" * 9):
            for max_len in (0, 1, 2, 3, 4, 5, 7, 24):
                out = contracts.clamp_text(s, max_len)
                assert len(out.encode()) <= max_len
                assert s.startswith(out)             # a prefix, never rewritten


class TestAcceptSlot:
    # accept_slot(is_default, is_known, named_count, max_slots)
    def test_default_always_accepted(self):
        # even with the named set full and the slot unknown
        assert contracts.accept_slot(True, False, 99, 4) is True

    def test_known_slot_always_accepted(self):
        assert contracts.accept_slot(False, True, 99, 4) is True

    def test_new_named_accepted_when_room(self):
        assert contracts.accept_slot(False, False, 3, 4) is True

    def test_new_named_rejected_when_full(self):
        assert contracts.accept_slot(False, False, 4, 4) is False

    def test_default_beats_full_even_when_unknown(self):
        # kills the `or -> and` mutant: is_default True, is_known False, full
        assert contracts.accept_slot(True, False, 10, 4) is True

    def test_truth_table_boundary_at_capacity(self):
        assert contracts.accept_slot(False, False, 0, 1) is True
        assert contracts.accept_slot(False, False, 1, 1) is False
