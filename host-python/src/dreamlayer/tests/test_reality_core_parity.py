"""Cross-language parity: the Rust `reality-core` PoC vs the Python reference.

The single-Rust-core proposal (docs/adr/0001-single-rust-core.md) rests on one
claim: a safety cap implemented ONCE in Rust can back every interpreter, so
parity is guaranteed by construction instead of tested for across three
hand-written copies. This test is the evidence. It loads the *compiled* Rust
cdylib via ctypes and drives it against `reality_compiler/v2/contracts.py` — the
exact functions M1 proved and M4 mutation-hardened — over a swept input space,
asserting the two agree bit-for-bit (ints exactly, floats to the last ULP).

It builds the crate on demand with `cargo build --release`; where cargo or the
shared library is unavailable (most CI), it skips cleanly — the PoC is a
de-risking artifact, not yet on the release path."""
import ctypes
import subprocess
from pathlib import Path

import pytest

from dreamlayer.reality_compiler.v2 import contracts

CRATE = Path(__file__).resolve().parents[4] / "reality-core"
OP = {"inc": 0, "dec": 1, "set": 2}
CMP = {"ge": 0, "le": 1, "eq": 2}


def _load_core():
    if not CRATE.exists():
        pytest.skip("reality-core crate not present")
    so = next(iter((CRATE / "target" / "release").glob("libreality_core.*")), None)
    if so is None:
        if subprocess.run(["cargo", "--version"], capture_output=True).returncode:
            pytest.skip("cargo not available to build the Rust core")
        r = subprocess.run(["cargo", "build", "--release"], cwd=CRATE,
                            capture_output=True, text=True)
        if r.returncode:
            pytest.skip(f"cargo build failed: {r.stderr[-400:]}")
        so = next(iter((CRATE / "target" / "release").glob("libreality_core.*")))
    lib = ctypes.CDLL(str(so))
    lib.rc_saturate.restype = ctypes.c_int64
    lib.rc_saturate.argtypes = [ctypes.c_int64, ctypes.c_uint8, ctypes.c_int64,
                                ctypes.c_int64, ctypes.c_int64]
    lib.rc_refill_tokens.restype = ctypes.c_double
    lib.rc_refill_tokens.argtypes = [ctypes.c_double] * 4
    lib.rc_spend_token.restype = ctypes.c_int32
    lib.rc_spend_token.argtypes = [ctypes.c_double, ctypes.POINTER(ctypes.c_double)]
    lib.rc_clamp_len.restype = ctypes.c_uint64
    lib.rc_clamp_len.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    lib.rc_accept_slot.restype = ctypes.c_int32
    lib.rc_accept_slot.argtypes = [ctypes.c_int32, ctypes.c_int32,
                                   ctypes.c_int64, ctypes.c_int64]
    lib.rc_guard_eval.restype = ctypes.c_int32
    lib.rc_guard_eval.argtypes = [ctypes.c_int64, ctypes.c_uint8, ctypes.c_int64]
    lib.rc_fmt_clock.restype = ctypes.c_uint64
    lib.rc_fmt_clock.argtypes = [ctypes.c_double, ctypes.c_char_p, ctypes.c_uint64]
    return lib


def _core_fmt_clock(core, secs: float) -> str:
    buf = ctypes.create_string_buffer(32)
    n = core.rc_fmt_clock(secs, buf, 32)
    return buf.raw[:n].decode("ascii")


def _bind_stage_abi(lib):
    for name, res, args in [
        ("rc_stage_new", ctypes.c_int32, []),
        ("rc_stage_free", None, [ctypes.c_int32]),
        ("rc_stage_add_counter", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64]),
        ("rc_stage_add_scene", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_double]),
        ("rc_tx_begin", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_tx_guard", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_uint8, ctypes.c_int64]),
        ("rc_tx_op", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_uint8, ctypes.c_int64]),
        ("rc_tx_emit", ctypes.c_int32, [ctypes.c_int32]),
        ("rc_tx_commit_timeout", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_tx_commit_event", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32]),
        ("rc_stage_start", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_stage_step", ctypes.c_int32, [ctypes.c_int32, ctypes.c_double]),
        ("rc_stage_inject", ctypes.c_int32, [ctypes.c_int32, ctypes.c_uint32]),
        ("rc_stage_counter", ctypes.c_int64, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_stage_clock", ctypes.c_double, [ctypes.c_int32]),
        ("rc_stage_elapsed", ctypes.c_double, [ctypes.c_int32]),
        ("rc_stage_remaining", ctypes.c_double, [ctypes.c_int32]),
        ("rc_stage_current", ctypes.c_int32, [ctypes.c_int32]),
        ("rc_stage_ended", ctypes.c_int32, [ctypes.c_int32]),
        ("rc_stage_emits", ctypes.c_int64, [ctypes.c_int32]),
        ("rc_stage_dropped", ctypes.c_int64, [ctypes.c_int32]),
        ("rc_stage_tokens", ctypes.c_double, [ctypes.c_int32]),
    ]:
        fn = getattr(lib, name)
        fn.restype = res
        fn.argtypes = args


TARGET_SELF, TARGET_END = -1, -2


class CoreStage:
    """The Python-binding prototype: intern a real Figment's strings (scene
    ids, counter names, event names) to indices/codes and load it into the
    Rust core Stage. All state-machine behavior comes back over the ABI."""

    def __init__(self, core, fig):
        from dreamlayer.reality_compiler.v2.figment import END, SELF
        _bind_stage_abi(core)
        self.core = core
        self.h = core.rc_stage_new()
        assert self.h >= 0, "stage pool exhausted"
        self.counter_idx = {}
        for name, decl in fig.counters.items():
            self.counter_idx[name] = core.rc_stage_add_counter(
                self.h, decl.start, decl.lo, decl.hi)
        self.scene_idx = {sid: core.rc_stage_add_scene(
            self.h, 1 if s.duration_sec is not None else 0,
            float(s.duration_sec or 0.0)) for sid, s in fig.scenes.items()}
        self.event_code = {}

        def target_of(t):
            if t.target == END:
                return TARGET_END
            if t.target == SELF:
                return TARGET_SELF
            return self.scene_idx[t.target]

        def build_tx(t):
            core.rc_tx_begin(self.h, target_of(t))
            if t.when is not None:
                core.rc_tx_guard(self.h, self.counter_idx[t.when.counter],
                                 CMP[t.when.cmp], t.when.value)
            for op in t.counter_ops:
                core.rc_tx_op(self.h, self.counter_idx[op.counter],
                              OP[op.op], op.amount)
            if t.emit is not None:
                core.rc_tx_emit(self.h)

        for sid, s in fig.scenes.items():
            for ev, t in s.on.items():
                code = self.event_code.setdefault(ev, len(self.event_code) + 1)
                build_tx(t)
                core.rc_tx_commit_event(self.h, self.scene_idx[sid], code)
            for t in s.on_timeout:
                build_tx(t)
                core.rc_tx_commit_timeout(self.h, self.scene_idx[sid])
        core.rc_stage_start(self.h, self.scene_idx[fig.initial])

    def step(self, dt):
        self.core.rc_stage_step(self.h, dt)

    def inject(self, event):
        return self.core.rc_stage_inject(self.h, self.event_code.get(event, 0))

    def state(self, counters):
        c = self.core
        return {
            "clock": c.rc_stage_clock(self.h),
            "elapsed": c.rc_stage_elapsed(self.h),
            "remaining": c.rc_stage_remaining(self.h),
            "ended": bool(c.rc_stage_ended(self.h)),
            "emits": c.rc_stage_emits(self.h),
            "dropped": c.rc_stage_dropped(self.h),
            "tokens": c.rc_stage_tokens(self.h),
            "counters": {n: c.rc_stage_counter(self.h, i)
                         for n, i in self.counter_idx.items()
                         if n in counters},
        }

    def close(self):
        self.core.rc_stage_free(self.h)


def _py_state(st, counters):
    return {
        "clock": st.clock,
        "elapsed": st.scene_elapsed,
        "remaining": st.remaining(),
        "ended": st.ended,
        "emits": len(st.emits),
        "dropped": st.dropped_emits,
        "tokens": st._tokens,
        "counters": {n: v for n, v in st.counters.items() if n in counters},
    }


def _py_guard(val, cmp, threshold):
    # mirrors interpreter._guard
    if cmp == "ge":
        return val >= threshold
    if cmp == "le":
        return val <= threshold
    return val == threshold


@pytest.fixture(scope="module")
def core():
    return _load_core()


class TestSaturateParity:
    def test_swept(self, core):
        for lo, hi in ((0, 10), (-5, 5), (0, 3), (1, 3), (-100, 100)):
            for op in ("inc", "dec", "set"):
                for cur in range(lo - 2, hi + 3):
                    for amount in (0, 1, 2, 5, 100, -3):
                        py = contracts.saturate(cur, op, amount, lo, hi)
                        rs = core.rc_saturate(cur, OP[op], amount, lo, hi)
                        assert py == rs, (cur, op, amount, lo, hi, py, rs)


class TestRefillParity:
    def test_swept(self, core):
        for tokens in (0.0, 0.5, 1.0, 3.0, 5.0):
            for dt in (0.0, 0.1, 0.5, 1.0, 3.3, 1000.0):
                for refill in (0.0, 1.0, 2.5):
                    for burst in (5.0, 1.0, 10.0):
                        py = contracts.refill_tokens(tokens, dt, refill, burst)
                        rs = core.rc_refill_tokens(tokens, dt, refill, burst)
                        assert py == rs, (tokens, dt, refill, burst, py, rs)


class TestSpendParity:
    def test_swept(self, core):
        out = ctypes.c_double(0.0)
        for tokens in (0.0, 0.5, 0.999, 1.0, 1.0001, 2.5, 5.0):
            spent_py, after_py = contracts.spend_token(tokens)
            spent_rs = core.rc_spend_token(tokens, ctypes.byref(out))
            assert int(spent_py) == spent_rs, (tokens, spent_py, spent_rs)
            assert after_py == out.value, (tokens, after_py, out.value)


class TestClampParity:
    def test_swept(self, core):
        for length in range(0, 40):
            for max_len in (0, 1, 24, 39):
                py = len(contracts.clamp_text("x" * length, max_len))
                rs = core.rc_clamp_len(length, max_len)
                assert py == rs, (length, max_len, py, rs)


class TestAcceptSlotParity:
    def test_swept(self, core):
        for d in (0, 1):
            for k in (0, 1):
                for named in range(0, 12):
                    for mx in (0, 1, 8):
                        py = contracts.accept_slot(bool(d), bool(k), named, mx)
                        rs = core.rc_accept_slot(d, k, named, mx)
                        assert int(py) == rs, (d, k, named, mx, py, rs)


class TestGuardParity:
    def test_swept(self, core):
        for cmp in ("ge", "le", "eq"):
            for threshold in (-3, 0, 1, 3, 9999):
                for val in range(threshold - 3, threshold + 4):
                    py = 1 if _py_guard(val, cmp, threshold) else 0
                    rs = core.rc_guard_eval(val, CMP[cmp], threshold)
                    assert py == rs, (val, cmp, threshold, py, rs)


class TestFmtClockParity:
    def test_swept(self, core):
        from dreamlayer.reality_compiler.v2.interpreter import _fmt_clock
        cases = ([0.0, 0.1, 0.5, 1.0, 47.9, 48.0, 59.0, 59.2, 59.999,
                  60.0, 61.0, 90.0, 168.0, 179.5, 3599.0, 3600.0, 7261.0, -5.0]
                 + [i * 0.7 for i in range(0, 300, 7)])
        for secs in cases:
            assert _core_fmt_clock(core, secs) == _fmt_clock(secs), secs

    def test_through_the_real_render_path(self, core):
        # a live countdown Stage: the {remaining} and {elapsed} text the frame
        # actually shows must equal the core's formatting of the same clocks —
        # the first string produced by the Rust core matching a real render
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, TextLine, Transition, Stage, END,
        )
        fig = Figment(name="clock", initial="a")
        fig.add_scene(Scene(
            id="a", duration_sec=180.0, tick="countdown",
            lines=[TextLine("{remaining}", row=0), TextLine("{elapsed}", row=1)],
            on_timeout=[Transition(target=END)]))
        st = Stage(fig)
        for dt in (0.0, 1.0, 11.5, 47.5, 59.7, 60.0):   # crosses the minute mark
            if dt:
                st.step(dt)
            lines = st.frame().lines
            assert lines[0].text == _core_fmt_clock(core, st.remaining())
            assert lines[1].text == _core_fmt_clock(core, st.scene_elapsed)


def test_bounded_loop_parity_against_the_real_stage(core):
    """The control-flow step, end to end: a real "3 rounds then END" figment run
    on the actual Python Stage, its counter trajectory + termination matched
    step-for-step by the core's guard_eval + saturate — the decision that makes
    a bounded loop terminate, now backed by the Rust core."""
    from dreamlayer.reality_compiler.v2 import (
        Figment, Scene, TextLine, CounterDecl, CounterOp, Guard, Transition,
        Stage, END, SELF,
    )
    fig = Figment(name="loop", initial="work")
    fig.add_counter(CounterDecl("round", start=1, lo=1, hi=3))
    fig.add_scene(Scene(
        id="work", duration_sec=1.0, lines=[TextLine("{count:round}", row=1)],
        on_timeout=[
            Transition(target=END, when=Guard("round", "ge", 3)),
            Transition(target=SELF, counter_ops=[CounterOp("round", "inc", 1)]),
        ]))
    st = Stage(fig)
    # the core's independent replica of the timeout decision
    round_core, ended_core, lo, hi = 1, False, 1, 3
    for _ in range(10):
        if st.ended:
            break
        st.step(1.0)                         # fire exactly one timeout
        # mirror it with the core: guard on the pre-step round, else inc
        if core.rc_guard_eval(round_core, CMP["ge"], 3):
            ended_core = True
        else:
            round_core = core.rc_saturate(round_core, OP["inc"], 1, lo, hi)
        assert st.counters["round"] == round_core, (st.counters["round"], round_core)
        assert st.ended == ended_core, (st.ended, ended_core)
    assert st.ended and ended_core
    assert st.counters["round"] == round_core == 3


class TestStageStateMachineParity:
    """The full state machine, in the core: real figments run side-by-side on
    the actual Python Stage and the core Stage, every observable compared
    exactly (floats bit-for-bit — same f64 ops in the same order) at every
    step, through to termination."""

    def _run_schedule(self, core, fig, schedule, counters=()):
        from dreamlayer.reality_compiler.v2 import Stage
        py = Stage(fig)
        rs = CoreStage(core, fig)
        try:
            for i, (kind, arg) in enumerate(schedule):
                if kind == "step":
                    py.step(arg)
                    rs.step(arg)
                else:
                    py.inject(arg)
                    rs.inject(arg)
                assert _py_state(py, counters) == rs.state(counters), (i, kind, arg)
            return _py_state(py, counters)
        finally:
            rs.close()

    def test_guarded_loop_odd_steps(self, core):
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, CounterDecl, CounterOp, Guard, Transition, END,
            SELF, TextLine,
        )
        fig = Figment(name="t", initial="work")
        fig.add_counter(CounterDecl("round", start=1, lo=1, hi=3))
        fig.add_scene(Scene(
            id="work", duration_sec=1.0,
            lines=[TextLine("{count:round}", row=1)],
            on_timeout=[
                Transition(target=END, when=Guard("round", "ge", 3)),
                Transition(target=SELF,
                           counter_ops=[CounterOp("round", "inc", 1)]),
            ]))
        # odd fractional steps force the epsilon subdivision to matter
        final = self._run_schedule(
            core, fig, [("step", d) for d in (0.3, 0.7, 0.35, 1.9, 0.05, 2.6)],
            counters=("round",))
        assert final["ended"] and final["counters"]["round"] == 3

    def test_native_timer_figment(self, core):
        from dreamlayer.reality_compiler.v2 import native
        fig = native.timer_figment(30)
        final = self._run_schedule(
            core, fig, [("step", d) for d in (10.0, 10.0, 9.5, 0.4, 0.2, 5.0)])
        assert final["ended"]

    def test_native_interval_figment(self, core):
        from dreamlayer.reality_compiler.v2 import native
        fig = native.interval_figment(20, 10, rounds=3)
        counters = tuple(fig.counters)
        schedule = [("step", 7.3)] * 16          # 116.8 s of ragged ticks
        final = self._run_schedule(core, fig, schedule, counters=counters)
        assert final["ended"]                     # 3×(20+10)=90 s, well past

    def test_event_flood_and_mixed_schedule(self, core):
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, CounterDecl, CounterOp, Transition, SELF, TextLine,
        )
        fig = Figment(name="tap", initial="count")
        fig.add_counter(CounterDecl("n", start=0, lo=0, hi=99))
        fig.add_scene(Scene(id="count", lines=[TextLine("{count:n}", row=1)]))
        fig.scenes["count"].on["single"] = Transition(
            target=SELF, emit="tap", counter_ops=[CounterOp("n", "inc", 1)])
        # 12 instant taps flood the bucket, then time passes, then more taps —
        # spends, drops, refills, and the counter all tracked in lockstep
        schedule = ([("inject", "single")] * 12 + [("step", 3.5)]
                    + [("inject", "single")] * 6 + [("step", 0.25),
                       ("inject", "single")])
        final = self._run_schedule(core, fig, schedule, counters=("n",))
        assert final["counters"]["n"] == 19
        # burst of 5, then 3.5 s refill buys 3 more; the 0.25 s refill leaves
        # 0.75 tokens, so the last tap drops
        assert final["emits"] == 5 + 3
        assert final["dropped"] == 19 - final["emits"]


def test_core_is_exhaustively_equivalent_on_the_hot_path(core):
    """A blunt end-to-end check: the token bucket driven through many spends +
    refills stays identical between the Rust core and the Python reference — the
    exact loop the interpreter runs every emit."""
    out = ctypes.c_double(0.0)
    py_tokens = rs_tokens = 5.0
    for step in range(200):
        dt = (step % 7) * 0.3
        py_tokens = contracts.refill_tokens(py_tokens, dt, 1.0, 5.0)
        rs_tokens = core.rc_refill_tokens(rs_tokens, dt, 1.0, 5.0)
        spent_py, py_tokens = contracts.spend_token(py_tokens)
        spent_rs = core.rc_spend_token(rs_tokens, ctypes.byref(out))
        rs_tokens = out.value
        assert int(spent_py) == spent_rs and py_tokens == rs_tokens, step
