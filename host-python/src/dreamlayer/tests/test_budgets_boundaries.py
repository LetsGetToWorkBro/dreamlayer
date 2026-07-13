"""Boundary table for budgets.verify() — the static proof that no figment ships
outside the constraint envelope.

test_rc2_budgets.py checks that each violation *fires*, but mostly with a coarse
"code in codes(fig)" and rarely at the boundary. Mutation testing showed the
cost: flip a `>` to `>=` or a `<` to `<=` on any cap and the suite stays green,
because nothing tests the value exactly at the limit vs one step over.

This pins every numeric/comparison check as a PAIR — a figment exactly at the
limit that must pass, and one a single step over that must trip the specific
code — so an off-by-one in the envelope fails the build. It also covers the
checks test_rc2_budgets omits (name length, counter/slot caps, counter-op cap,
emit-tag length, guard comparator, duration range, glyph caps/coords, cadence,
and the BLE-flood rate boundary at exactly the refill rate).

This is a *logic* adequacy suite: it targets the comparisons and branches, not
the diagnostic message strings (which mutmut also mutates but which are
engineer-facing text, not behavior).

Result: the mutation score rose from ~37% to ~69% (500/720 killed). Every
*verdict-affecting* mutant — every comparison boundary, valid-token acceptance,
branch, capability/slot check, reachability edge, and BLE-flood-detection path —
is now killed. The residual ~215 are non-behavioral: mutmut wraps/re-cases each
of the ~40 diagnostic message strings and blanks each ``bad(code, msg, scene)``
message/scene argument (killing those would need brittle exact-text and
per-check scene-tag assertions), plus three _cycle_analysis mutants of which two
are provably equivalent (a zero-time cycle is impossible given MIN_SCENE_SEC≥0.5
— the code says as much; and ``target >= start`` equals ``target > start`` since
``target == start`` is handled by the branch above) and one is a cycle-
enumeration reshuffle that doesn't change the flood verdict. The enforced
zero-survivor mutmut gate stays on contracts.py; this is coverage hardening
verified by mutation testing."""
from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, PulseSpec,
    CounterDecl, CounterOp, Guard, Transition, END, SELF, verify,
)
from dreamlayer.reality_compiler.v2.figment import (
    CadenceSpec, GlyphSpec,
    MAX_SCENES, MAX_COUNTERS, MAX_LINES, MAX_TEXT_LEN, MAX_COUNTER_OPS,
    MAX_BRANCHES, MAX_PULSE_HZ, MIN_SCENE_SEC, MAX_SCENE_SEC,
    EMIT_REFILL_PER_S, MAX_EMIT_TAG_LEN, MAX_NAME_LEN, MAX_GLYPHS,
    MAX_GLYPH_POINTS, MAX_SLOTS,
)


def base(duration=10.0) -> Figment:
    fig = Figment(name="t", initial="a")
    fig.add_scene(Scene(id="a", duration_sec=duration,
                        lines=[TextLine("hi", row=1)],
                        on_timeout=[Transition(target=END)]))
    return fig


def codes(fig) -> set[str]:
    return {v.code for v in verify(fig).violations}


def warns(fig) -> set[str]:
    return {w.code for w in verify(fig).warnings}


# ---------------------------------------------------------------------------
# Structural caps — each a pass/trip pair straddling the exact limit
# ---------------------------------------------------------------------------

class TestNameLength:
    def test_at_limit_passes(self):
        fig = base(); fig.name = "x" * MAX_NAME_LEN
        assert "name" not in codes(fig)

    def test_over_limit_trips(self):
        fig = base(); fig.name = "x" * (MAX_NAME_LEN + 1)
        assert "name" in codes(fig)

    def test_empty_name_trips(self):
        fig = base(); fig.name = ""
        assert "name" in codes(fig)


class TestSceneCount:
    def _n(self, n):
        fig = Figment(name="t", initial="s0")
        for i in range(n):
            fig.add_scene(Scene(id=f"s{i}", duration_sec=1.0,
                                on_timeout=[Transition(target=END)]))
        return fig

    def test_at_limit_passes(self):
        assert "scene_count" not in codes(self._n(MAX_SCENES))

    def test_over_limit_trips(self):
        assert "scene_count" in codes(self._n(MAX_SCENES + 1))


class TestCounterCount:
    def _n(self, n):
        fig = base()
        for i in range(n):
            fig.add_counter(CounterDecl(f"c{i}"))
        return fig

    def test_at_limit_passes(self):
        assert "counter_count" not in codes(self._n(MAX_COUNTERS))

    def test_over_limit_trips(self):
        assert "counter_count" in codes(self._n(MAX_COUNTERS + 1))


class TestSlotCount:
    def _slots(self, n):
        # n named slots, one per line, ≤MAX_LINES lines per scene
        fig = Figment(name="t", initial="sc0")
        k, sc = 0, 0
        while k < n:
            lines = []
            for row in range(min(MAX_LINES, n - k)):
                lines.append(TextLine("{slot:s%d}" % k, row=row))
                k += 1
            fig.add_scene(Scene(id=f"sc{sc}", lines=lines))
            sc += 1
        return fig

    def test_at_limit_passes(self):
        assert "slot_count" not in codes(self._slots(MAX_SLOTS))

    def test_over_limit_trips(self):
        assert "slot_count" in codes(self._slots(MAX_SLOTS + 1))


class TestSlotName:
    def test_over_length_slot_name_trips(self):
        fig = Figment(name="t", initial="a")
        long_name = "s" * (MAX_NAME_LEN + 1)
        fig.add_scene(Scene(id="a", lines=[TextLine("{slot:%s}" % long_name)]))
        assert "slot_name" in codes(fig)

    def test_at_limit_slot_name_passes(self):
        # exactly MAX_NAME_LEN is allowed (>, not >=)
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a",
                            lines=[TextLine("{slot:%s}" % ("s" * MAX_NAME_LEN))]))
        assert "slot_name" not in codes(fig)


class TestCapabilityContract:
    def test_emitted_capability_must_be_declared(self):
        fig = base()
        fig.scenes["a"].on["single"] = Transition(target=SELF, emit="ask")
        assert "capability_undeclared" in codes(fig)      # emits ask, no requires
        fig.meta["requires"] = ["ask"]
        assert "capability_undeclared" not in codes(fig)   # now declared

    def test_unknown_declared_capability_trips(self):
        fig = base()
        fig.meta["requires"] = ["teleport"]                # not a real capability
        assert "capability_unknown" in codes(fig)

    def test_passive_declare_without_emit_is_allowed(self):
        # declaring a real capability you don't emit is fine (declared ⊇ emitted)
        fig = base()
        fig.meta["requires"] = ["translate"]
        assert "capability_undeclared" not in codes(fig)
        assert "capability_unknown" not in codes(fig)


class TestInitialAndBattery:
    def test_missing_initial(self):
        fig = Figment(name="t", initial="ghost")
        fig.add_scene(Scene(id="a", lines=[]))
        assert "initial" in codes(fig)

    def test_battery_low_bound(self):
        fig = base(); fig.battery_below = 1        # inclusive lower bound
        fig.scenes["a"].on["battery_low"] = Transition(target=END)
        assert "battery" not in codes(fig)
        fig.battery_below = 0
        assert "battery" in codes(fig)

    def test_battery_high_bound(self):
        fig = base(); fig.battery_below = 99       # inclusive upper bound
        fig.scenes["a"].on["battery_low"] = Transition(target=END)
        assert "battery" not in codes(fig)
        fig.battery_below = 100
        assert "battery" in codes(fig)

    def test_battery_set_without_listener_warns(self):
        fig = base(); fig.battery_below = 20
        assert "battery" in warns(fig)


# ---------------------------------------------------------------------------
# Transition checks
# ---------------------------------------------------------------------------

class TestTransition:
    def test_unknown_target(self):
        fig = base(); fig.scenes["a"].on["single"] = Transition(target="ghost")
        assert "target" in codes(fig)

    def test_self_and_end_targets_ok(self):
        fig = base(); fig.scenes["a"].on["single"] = Transition(target=SELF)
        assert "target" not in codes(fig)

    def test_counter_ops_cap(self):
        fig = base(); fig.add_counter(CounterDecl("n"))
        ops = [CounterOp("n", "inc", 1) for _ in range(MAX_COUNTER_OPS)]
        fig.scenes["a"].on["single"] = Transition(target=SELF, counter_ops=ops)
        assert "counter_ops" not in codes(fig)
        fig.scenes["a"].on["single"] = Transition(
            target=SELF, counter_ops=ops + [CounterOp("n", "inc", 1)])
        assert "counter_ops" in codes(fig)

    def test_unknown_counter_op(self):
        fig = base(); fig.add_counter(CounterDecl("n"))
        fig.scenes["a"].on["single"] = Transition(
            target=SELF, counter_ops=[CounterOp("n", "mul", 1)])
        assert "counter" in codes(fig)

    def test_emit_tag_length(self):
        fig = base()
        fig.scenes["a"].on["single"] = Transition(
            target=SELF, emit="x" * MAX_EMIT_TAG_LEN)
        assert "emit_tag" not in codes(fig)
        fig.scenes["a"].on["single"] = Transition(
            target=SELF, emit="x" * (MAX_EMIT_TAG_LEN + 1))
        assert "emit_tag" in codes(fig)

    def test_empty_emit_tag_trips(self):
        fig = base()
        fig.scenes["a"].on["single"] = Transition(target=SELF, emit="")
        assert "emit_tag" in codes(fig)

    def test_guard_only_on_timeout(self):
        fig = base(); fig.add_counter(CounterDecl("n"))
        fig.scenes["a"].on["single"] = Transition(
            target=END, when=Guard("n", "ge", 1))
        assert "guard" in codes(fig)

    def test_guard_unknown_comparator(self):
        fig = base(); fig.add_counter(CounterDecl("n"))
        fig.scenes["a"].on_timeout = [
            Transition(target=SELF, when=Guard("n", "ne", 1)),
            Transition(target=END)]
        assert "guard" in codes(fig)

    def test_guard_undeclared_counter(self):
        fig = base()
        fig.scenes["a"].on_timeout = [
            Transition(target=SELF, when=Guard("ghost", "ge", 1)),
            Transition(target=END)]
        assert "guard" in codes(fig)


# ---------------------------------------------------------------------------
# Per-scene structural + text
# ---------------------------------------------------------------------------

class TestValidTokensAccepted:
    """The whitelists must ACCEPT their members — mutating a valid token in the
    ('inc','dec','set') / ('ge','le','eq') tuples would reject legitimate
    figments, which only a "this valid op does NOT trip" test can catch."""

    def test_every_counter_op_is_accepted(self):
        for op in ("inc", "dec", "set"):
            fig = base(); fig.add_counter(CounterDecl("n"))
            fig.scenes["a"].on["single"] = Transition(
                target=SELF, counter_ops=[CounterOp("n", op, 1)])
            assert "counter" not in codes(fig), op

    def test_every_guard_comparator_is_accepted(self):
        for cmp in ("ge", "le", "eq"):
            fig = base(); fig.add_counter(CounterDecl("n", lo=0, hi=9))
            fig.scenes["a"].on_timeout = [
                Transition(target=SELF, when=Guard("n", cmp, 1)),
                Transition(target=END)]
            assert "guard" not in codes(fig), cmp

    def test_every_tick_token_is_accepted(self):
        for tk in ("countdown", "countup"):
            fig = base(); fig.scenes["a"].tick = tk
            assert "tick" not in codes(fig), tk


class TestSceneAttribution:
    def test_violation_carries_its_scene(self):
        # a per-scene violation must be tagged with the scene id (not None), so
        # teach.py can point the user at the right beat
        fig = base(); fig.scenes["a"].lines[0].color = "#f00"
        viol = next(v for v in verify(fig).violations if v.code == "color")
        assert viol.scene == "a"

    def test_violation_carries_its_message(self):
        # the diagnostic message must be present (not blanked)
        fig = base(); fig.scenes["a"].lines[0].color = "#f00"
        viol = next(v for v in verify(fig).violations if v.code == "color")
        assert viol.message and "palette" in viol.message


class TestLinesAndText:
    def test_line_cap(self):
        fig = base()
        fig.scenes["a"].lines = [TextLine("x", row=r) for r in range(MAX_LINES)]
        assert "lines" not in codes(fig)
        fig.scenes["a"].lines.append(TextLine("y", row=0))
        assert "lines" in codes(fig)

    def test_text_length(self):
        fig = base(); fig.scenes["a"].lines[0].content = "x" * MAX_TEXT_LEN
        assert "text_len" not in codes(fig)
        fig.scenes["a"].lines[0].content = "x" * (MAX_TEXT_LEN + 1)
        assert "text_len" in codes(fig)

    def test_row_range(self):
        fig = base(); fig.scenes["a"].lines[0].row = MAX_LINES - 1
        assert "row" not in codes(fig)
        fig.scenes["a"].lines[0].row = MAX_LINES        # == MAX_LINES is invalid
        assert "row" in codes(fig)
        fig.scenes["a"].lines[0].row = -1
        assert "row" in codes(fig)

    def test_duplicate_row(self):
        fig = base()
        fig.scenes["a"].lines = [TextLine("a", row=0), TextLine("b", row=0)]
        assert "row" in codes(fig)

    def test_color_and_size_tokens(self):
        fig = base(); fig.scenes["a"].lines[0].color = "#FF0000"
        assert "color" in codes(fig)
        fig = base(); fig.scenes["a"].lines[0].size = "xl"
        assert "size" in codes(fig)


class TestTemporal:
    def test_duration_min_boundary(self):
        assert "duration" not in codes(base(duration=MIN_SCENE_SEC))
        assert "duration" in codes(base(duration=MIN_SCENE_SEC - 0.01))

    def test_duration_max_boundary(self):
        assert "duration" not in codes(base(duration=MAX_SCENE_SEC))
        assert "duration" in codes(base(duration=MAX_SCENE_SEC + 1))

    def test_both_durations_conflict(self):
        fig = base()
        fig.scenes["a"].duration_range = (1.0, 2.0)     # plus the fixed one
        assert "duration" in codes(fig)

    def test_duration_range_validity(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_range=(2.0, 1.0),   # lo > hi
                            lines=[], on_timeout=[Transition(target=END)]))
        assert "duration" in codes(fig)

    def test_duration_range_valid_passes(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_range=(1.0, 2.0),
                            lines=[], on_timeout=[Transition(target=END)]))
        assert "duration" not in codes(fig)

    def _range(self, lo, hi):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_range=(lo, hi),
                            lines=[], on_timeout=[Transition(target=END)]))
        return fig

    def test_duration_range_boundaries_inclusive(self):
        # MIN<=lo<=hi<=MAX, every relation inclusive: exact-endpoint ranges pass
        assert "duration" not in codes(self._range(MIN_SCENE_SEC, MIN_SCENE_SEC))
        assert "duration" not in codes(self._range(MIN_SCENE_SEC, MAX_SCENE_SEC))
        assert "duration" in codes(self._range(MIN_SCENE_SEC - 0.01, 2.0))
        assert "duration" in codes(self._range(1.0, MAX_SCENE_SEC + 1))

    def test_timeout_requires_duration(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", lines=[],
                            on_timeout=[Transition(target=END)]))
        assert "timeout" in codes(fig)

    def test_timed_requires_timeout(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=5.0, lines=[]))
        assert "timeout" in codes(fig)

    def test_branch_cap(self):
        fig = base()
        fig.add_counter(CounterDecl("n", lo=0, hi=99))
        br = [Transition(target=SELF, when=Guard("n", "ge", i + 1))
              for i in range(MAX_BRANCHES - 1)]
        fig.scenes["a"].on_timeout = br + [Transition(target=END)]
        assert "branches" not in codes(fig)
        fig.scenes["a"].on_timeout = (
            br + [Transition(target=SELF, when=Guard("n", "ge", 9)),
                  Transition(target=END)])
        assert "branches" in codes(fig)

    def test_last_branch_must_be_default(self):
        fig = base(); fig.add_counter(CounterDecl("n"))
        fig.scenes["a"].on_timeout = [
            Transition(target=END, when=Guard("n", "ge", 1))]
        assert "branches" in codes(fig)

    def test_tick_unknown_and_countdown_needs_duration(self):
        fig = base(); fig.scenes["a"].tick = "spin"
        assert "tick" in codes(fig)
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", tick="countdown", lines=[]))
        assert "tick" in codes(fig)


class TestPulse:
    def test_rate_boundary(self):
        fig = base(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=MAX_PULSE_HZ)
        assert "pulse_rate" not in codes(fig)
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=MAX_PULSE_HZ + 0.1)
        assert "pulse_rate" in codes(fig)

    def test_rate_must_be_positive(self):
        fig = base(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=0.0)
        assert "pulse_rate" in codes(fig)

    def test_low_positive_rate_is_allowed(self):
        # a rate in (0, 1] must pass — pins the `<= 0` lower bound (not `<= 1`)
        fig = base(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=1.0)
        assert "pulse_rate" not in codes(fig)

    def test_window_must_fit(self):
        fig = base(duration=5.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=5.0, rate_hz=2.0)  # == dur ok
        assert "pulse" not in codes(fig)
        fig.scenes["a"].pulse = PulseSpec(window_sec=5.01, rate_hz=2.0)
        assert "pulse" in codes(fig)

    def test_window_must_be_positive(self):
        fig = base(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=0.0, rate_hz=2.0)
        assert "pulse" in codes(fig)                      # window 0 is invalid

    def test_small_positive_window_allowed(self):
        # a window in (0, 1] within the duration must pass — pins `<= 0` (not `<= 1`)
        fig = base(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=0.5, rate_hz=2.0)
        assert "pulse" not in codes(fig)

    def test_pulse_on_untimed_scene(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", lines=[],
                            pulse=PulseSpec(window_sec=1.0, rate_hz=2.0)))
        assert "pulse" in codes(fig)

    def test_pulse_color_token(self):
        fig = base(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=2.0, color="#f00")
        assert "color" in codes(fig)


class TestPaint:
    def _glyph(self, points=None, color="accent_attention", width="md"):
        return GlyphSpec(points=points or [(0.1, 0.1), (0.9, 0.9)],
                         color=color, width=width)

    def test_glyph_cap(self):
        fig = base()
        fig.scenes["a"].glyphs = [self._glyph() for _ in range(MAX_GLYPHS)]
        assert "glyphs" not in codes(fig)
        fig.scenes["a"].glyphs.append(self._glyph())
        assert "glyphs" in codes(fig)

    def test_glyph_point_count(self):
        fig = base()
        fig.scenes["a"].glyphs = [self._glyph(points=[(0.5, 0.5)])]   # 1 < 2
        assert "glyph_points" in codes(fig)
        fig = base()
        many = [(i / (MAX_GLYPH_POINTS + 1), 0.5) for i in range(MAX_GLYPH_POINTS + 1)]
        fig.scenes["a"].glyphs = [self._glyph(points=many)]
        assert "glyph_points" in codes(fig)

    def test_glyph_points_at_cap_pass(self):
        fig = base()
        pts = [(i / MAX_GLYPH_POINTS, 0.5) for i in range(MAX_GLYPH_POINTS)]
        fig.scenes["a"].glyphs = [self._glyph(points=pts)]
        assert "glyph_points" not in codes(fig)

    def test_two_points_is_the_inclusive_minimum(self):
        # exactly 2 points is a valid stroke (2 <=, not 3 <= or 2 <)
        fig = base()
        fig.scenes["a"].glyphs = [self._glyph(points=[(0.1, 0.1), (0.9, 0.9)])]
        assert "glyph_points" not in codes(fig)

    def test_glyph_coord_range(self):
        # both axes bounded: a point past 1.0 on x OR y trips; 0 and 1 inclusive
        for pt in ((1.5, 0.5), (0.5, 1.5), (-0.1, 0.5), (0.5, -0.1)):
            fig = base()
            fig.scenes["a"].glyphs = [self._glyph(points=[(0.0, 0.0), pt])]
            assert "glyph_coord" in codes(fig), pt
        fig = base()
        fig.scenes["a"].glyphs = [self._glyph(points=[(0.0, 0.0), (1.0, 1.0)])]
        assert "glyph_coord" not in codes(fig)     # 0 and 1 inclusive

    def test_glyph_color_and_width(self):
        fig = base()
        fig.scenes["a"].glyphs = [self._glyph(color="#abc")]
        assert "color" in codes(fig)
        fig = base()
        fig.scenes["a"].glyphs = [self._glyph(width="xl")]
        assert "glyph_width" in codes(fig)


class TestCadence:
    def _cad(self, in_s, hold_s, out_s):
        fig = base()
        fig.scenes["a"].cadence = CadenceSpec(in_s=in_s, hold_s=hold_s, out_s=out_s)
        return fig

    def test_any_negative_segment_trips(self):
        # each of the three segments is checked — including hold_s, which a
        # min() dropping an argument would miss
        assert "cadence" in codes(self._cad(-1.0, 1.0, 1.0))
        assert "cadence" in codes(self._cad(1.0, -1.0, 1.0))
        assert "cadence" in codes(self._cad(1.0, 1.0, -1.0))

    def test_zero_segment_is_allowed(self):
        # a zero segment is non-negative → fine, as long as the period is valid;
        # pins the `< 0` bound (not `<= 0` or `< 1`)
        assert "cadence" not in codes(self._cad(0.0, 1.0, 1.0))

    def test_period_below_min(self):
        assert "cadence" in codes(self._cad(0.1, 0.1, 0.1))   # period 0.3 < MIN

    def test_period_at_min_is_allowed(self):
        # period exactly MIN_SCENE_SEC passes (inclusive lower bound)
        assert "cadence" not in codes(self._cad(MIN_SCENE_SEC, 0.0, 0.0))

    def test_period_at_max_is_allowed(self):
        # period exactly MAX_SCENE_SEC passes (inclusive upper bound)
        assert "cadence" not in codes(self._cad(MAX_SCENE_SEC, 0.0, 0.0))

    def test_valid_cadence_passes(self):
        assert "cadence" not in codes(self._cad(1.0, 1.0, 1.0))


# ---------------------------------------------------------------------------
# BLE budget — the flood boundary is exactly the refill rate
# ---------------------------------------------------------------------------

class TestBleBudget:
    def _self_loop(self, secs):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=secs, lines=[],
                            on_timeout=[Transition(target=SELF, emit="x")]))
        return fig

    def test_rate_at_budget_passes(self):
        # exactly EMIT_REFILL_PER_S/s is allowed (>, not >=): 1 emit / 1.0s
        report = verify(self._self_loop(1.0 / EMIT_REFILL_PER_S))
        assert report.ok and report.worst_emit_per_sec == EMIT_REFILL_PER_S

    def test_rate_over_budget_trips(self):
        # just faster than the refill: 1 emit / 0.5s = 2/s > 1/s
        assert "ble_flood" in codes(self._self_loop(0.5))

    def test_no_emit_no_rate(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=0.5, lines=[],
                            on_timeout=[Transition(target=SELF)]))
        assert verify(fig).worst_emit_per_sec == 0.0

    def test_untimed_scene_before_flood_is_skipped_not_aborted(self):
        # an untimed scene earlier in iteration must be `continue`d past when
        # building the timeout graph — a `break` there would abandon the rest,
        # missing the flooding cycle that follows
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="z", lines=[TextLine("x", row=0)]))   # untimed
        fig.add_scene(Scene(id="a", duration_sec=0.5, lines=[],
                            on_timeout=[Transition(target=SELF, emit="x")]))
        assert "ble_flood" in codes(fig)

    def test_end_branch_before_emit_branch_is_skipped_not_aborted(self):
        # an END timeout branch ahead of the emitting cycle branch must be
        # `continue`d past, not `break`ed on — else the emit edge is never
        # added and the flood goes undetected
        fig = Figment(name="t", initial="a")
        fig.add_counter(CounterDecl("n", lo=0, hi=99))
        fig.add_scene(Scene(id="a", duration_sec=0.5, lines=[], on_timeout=[
            Transition(target=END, when=Guard("n", "ge", 99)),
            Transition(target=SELF, emit="x")]))
        assert "ble_flood" in codes(fig)


# ---------------------------------------------------------------------------
# Report object + warnings
# ---------------------------------------------------------------------------

class TestReport:
    def test_ok_flag_and_counts(self):
        fig = base(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=10, rate_hz=3.0)
        r = verify(fig)
        assert r.ok is True
        assert r.scene_count == 1
        assert r.worst_display_hz == 3.0          # max(1.0 baseline, pulse rate)

    def test_display_hz_baseline_is_one(self):
        assert verify(base()).worst_display_hz == 1.0

    def test_unreachable_scene_warns_not_fails(self):
        fig = base()
        fig.add_scene(Scene(id="island", lines=[]))
        r = verify(fig)
        assert r.ok and "unreachable" in {w.code for w in r.warnings}

    def test_reachable_chain_has_no_unreachable_warning(self):
        # a→b→c all reachable by traversing timeout/event edges: the reachability
        # walk must visit the whole chain (pins the stack init, the continue in
        # the pop loop, and the target-expansion edge filter)
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=1.0,
                            on_timeout=[Transition(target="b")]))
        fig.add_scene(Scene(id="b", duration_sec=1.0,
                            on_timeout=[Transition(target="c")]))
        fig.add_scene(Scene(id="c", duration_sec=1.0,
                            on_timeout=[Transition(target=END)]))
        r = verify(fig)
        assert r.ok
        assert not any(w.code == "unreachable" for w in r.warnings)

    def test_back_edge_graph_stays_fully_reachable(self):
        # a back edge (b→a) makes the reachability walk re-encounter an
        # already-seen node while another scene is still queued; the pop loop
        # must `continue` past the dup, not `break` and abandon the queue —
        # else a genuinely reachable scene is falsely flagged unreachable
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=1.0,
                            on_timeout=[Transition(target="b")]))
        fig.add_scene(Scene(id="b", duration_sec=1.0,
                            on={"single": Transition(target="c")},
                            on_timeout=[Transition(target="a")]))   # back edge
        fig.add_scene(Scene(id="c", duration_sec=1.0,
                            on_timeout=[Transition(target=END)]))
        r = verify(fig)
        assert not any(w.code == "unreachable" for w in r.warnings)

    def test_worst_emit_is_zero_when_graph_analysis_is_skipped(self):
        # a structurally invalid figment skips cycle analysis; the report's
        # emit rate must still be a number (0.0), not left unset
        fig = base(); fig.name = ""          # a structural violation
        assert verify(fig).worst_emit_per_sec == 0.0

    def test_beat_provenance_on_violation(self):
        fig = base()
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=30.0)
        fig.meta["scene_beats"] = {"a": 7}
        assert verify(fig).violations[0].beat == 7
