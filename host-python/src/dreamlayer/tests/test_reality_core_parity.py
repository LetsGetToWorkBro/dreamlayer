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


# The loadable cdylib per platform. NOT a glob: cargo also emits an .rlib in
# the same directory (the crate builds both types), and a wildcard picks it up
# — ctypes then fails with "invalid ELF header" (this broke CI; the local glob
# happened to return the .so first).
_DYLIB_NAMES = ("libreality_core.so", "libreality_core.dylib", "reality_core.dll")


def _find_dylib():
    release = CRATE / "target" / "release"
    return next((release / n for n in _DYLIB_NAMES if (release / n).exists()), None)


def _load_core():
    if not CRATE.exists():
        pytest.skip("reality-core crate not present")
    so = _find_dylib()
    if so is None:
        if subprocess.run(["cargo", "--version"], capture_output=True).returncode:
            pytest.skip("cargo not available to build the Rust core")
        r = subprocess.run(["cargo", "build", "--release"], cwd=CRATE,
                            capture_output=True, text=True)
        if r.returncode:
            pytest.skip(f"cargo build failed: {r.stderr[-400:]}")
        so = _find_dylib()
        if so is None:
            pytest.skip("cargo build produced no loadable cdylib")
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
    lib.rc_clamp_text_len.restype = ctypes.c_uint64
    lib.rc_clamp_text_len.argtypes = [ctypes.c_char_p, ctypes.c_uint64,
                                      ctypes.c_uint64]
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
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_double, ctypes.c_int32]),
        ("rc_stage_scene_range", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_double, ctypes.c_double]),
        ("rc_stage_set_battery", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32]),
        ("rc_stage_battery_level", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_stage_seed", ctypes.c_int32, [ctypes.c_int32, ctypes.c_uint64]),
        ("rc_tx_begin", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_tx_guard", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_uint8, ctypes.c_int64]),
        ("rc_tx_op", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_uint8, ctypes.c_int64]),
        ("rc_tx_emit", ctypes.c_int32, [ctypes.c_int32]),
        ("rc_tx_commit_timeout", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_tx_commit_event", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_uint32]),
        ("rc_stage_add_line", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_line_lit", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p,
          ctypes.c_uint64]),
        ("rc_line_tok", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_uint8,
          ctypes.c_uint32]),
        ("rc_stage_text", ctypes.c_int32,
         [ctypes.c_int32, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint64]),
        ("rc_stage_render_line", ctypes.c_int64,
         [ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p, ctypes.c_uint64]),
        ("rc_stage_line_count", ctypes.c_int32, [ctypes.c_int32]),
        ("rc_stage_start", ctypes.c_int32, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_stage_step", ctypes.c_int32, [ctypes.c_int32, ctypes.c_double]),
        ("rc_stage_inject", ctypes.c_int32, [ctypes.c_int32, ctypes.c_uint32]),
        ("rc_stage_counter", ctypes.c_int64, [ctypes.c_int32, ctypes.c_int32]),
        ("rc_stage_clock", ctypes.c_double, [ctypes.c_int32]),
        ("rc_stage_elapsed", ctypes.c_double, [ctypes.c_int32]),
        ("rc_stage_last_elapsed", ctypes.c_double, [ctypes.c_int32]),
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
TOK = {"remaining": 1, "remaining_s": 2, "elapsed": 3, "elapsed_ms": 4,
       "slot": 5, "count": 6}
# order matters: remaining_s before remaining, elapsed_ms before elapsed
_TOKEN_RE = __import__("re").compile(
    r"\{remaining_s\}|\{remaining\}|\{elapsed_ms\}|\{elapsed\}"
    r"|\{slot:(\w+)\}|\{slot\}|\{count:(\w+)\}")


class CoreStage:
    """The Python-binding prototype: intern a real Figment's strings (scene
    ids, counter names, event names, slot names) to indices/codes, tokenize
    its line templates, and load everything into the Rust core Stage. All
    interpreter behavior — stepping, guards, slots, rendering — comes back
    over the ABI."""

    def __init__(self, core, fig, battery_level=100, seed=None):
        from dreamlayer.reality_compiler.v2.figment import END, SELF
        _bind_stage_abi(core)
        self.core = core
        self.h = core.rc_stage_new()
        assert self.h >= 0, "stage pool exhausted"
        self.counter_idx = {}
        for name, decl in fig.counters.items():
            self.counter_idx[name] = core.rc_stage_add_counter(
                self.h, decl.start, decl.lo, decl.hi)
        self.scene_idx = {}
        for sid, s in fig.scenes.items():
            self.scene_idx[sid] = core.rc_stage_add_scene(
                self.h, 1 if s.duration_sec is not None else 0,
                float(s.duration_sec or 0.0), 1 if s.tick else 0)
            if s.duration_range is not None:
                lo, hi = s.duration_range
                core.rc_stage_scene_range(self.h, self.scene_idx[sid], lo, hi)
        self.event_code = {}
        self.slot_code = {}   # named slots; "" (default) is code 0 in the core

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
            for ln in s.lines:
                self._load_line(sid, ln.content)
        if fig.battery_below is not None:
            code = self.event_code.setdefault(
                "battery_low", len(self.event_code) + 1)
            core.rc_stage_set_battery(
                self.h, fig.battery_below, battery_level, code)
        if seed is not None:
            core.rc_stage_seed(self.h, seed)
        core.rc_stage_start(self.h, self.scene_idx[fig.initial])

    def _slot(self, name):
        if name == "":
            return 0
        return self.slot_code.setdefault(name, len(self.slot_code) + 1)

    def _load_line(self, sid, content):
        """Tokenize one authored template into core segments — the parse the
        interpreters redo per frame happens exactly once here."""
        core, sc = self.core, self.scene_idx[sid]
        li = core.rc_stage_add_line(self.h, sc)

        def lit(text):
            if text:
                b = text.encode("utf-8")
                core.rc_line_lit(self.h, sc, li, b, len(b))

        pos = 0
        for m in _TOKEN_RE.finditer(content):
            lit(content[pos:m.start()])
            tok = m.group(0)
            if tok == "{remaining}":
                core.rc_line_tok(self.h, sc, li, TOK["remaining"], 0)
            elif tok == "{remaining_s}":
                core.rc_line_tok(self.h, sc, li, TOK["remaining_s"], 0)
            elif tok == "{elapsed}":
                core.rc_line_tok(self.h, sc, li, TOK["elapsed"], 0)
            elif tok == "{elapsed_ms}":
                core.rc_line_tok(self.h, sc, li, TOK["elapsed_ms"], 0)
            elif tok == "{slot}":
                core.rc_line_tok(self.h, sc, li, TOK["slot"], 0)
            elif m.group(1) is not None:      # {slot:name}
                core.rc_line_tok(self.h, sc, li, TOK["slot"], self._slot(m.group(1)))
            elif m.group(2) is not None:      # {count:name}
                if m.group(2) in self.counter_idx:
                    core.rc_line_tok(self.h, sc, li, TOK["count"],
                                     self.counter_idx[m.group(2)])
                else:
                    lit(tok)   # undeclared counter stays literal (reference semantics)
            pos = m.end()
        lit(content[pos:])

    def step(self, dt):
        self.core.rc_stage_step(self.h, dt)

    def inject(self, event, text=None):
        """Mirror Stage.inject: a text[:name] event stores the slot value,
        then fires the base "text" trigger; everything else dispatches."""
        if event == "text" or event.startswith("text:"):
            name = event[5:] if event.startswith("text:") else ""
            if text is not None:
                b = text.encode("utf-8")
                self.core.rc_stage_text(self.h, self._slot(name), b, len(b))
            return self.core.rc_stage_inject(
                self.h, self.event_code.get("text", 0))
        return self.core.rc_stage_inject(self.h, self.event_code.get(event, 0))

    def render_lines(self):
        # frame-assembly policy mirrors Stage.frame(): after END the display
        # clears (an empty ended frame) — presentation, so it lives here in
        # the binding, like pulse phase and cadence do
        if self.core.rc_stage_ended(self.h):
            return []
        n = self.core.rc_stage_line_count(self.h)
        out = []
        for i in range(max(0, n)):
            buf = ctypes.create_string_buffer(64)
            ln = self.core.rc_stage_render_line(self.h, i, buf, 64)
            out.append(buf.raw[:ln].decode("utf-8") if ln >= 0 else None)
        return out

    def state(self, counters):
        c = self.core
        return {
            "clock": c.rc_stage_clock(self.h),
            "elapsed": c.rc_stage_elapsed(self.h),
            "last_elapsed": c.rc_stage_last_elapsed(self.h),
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
        "last_elapsed": st._last_elapsed,
        "remaining": st.remaining(),
        "ended": st.ended,
        "emits": len(st.emits),
        "dropped": st.dropped_emits,
        "tokens": st._tokens,
        "counters": {n: v for n, v in st.counters.items() if n in counters},
    }


class SplitMix:
    """The core's duration_range stream, mirrored: hand this to the reference
    Stage as its rng and seed the core identically — bit-identical rolls."""

    def __init__(self, seed):
        self.s = seed & (2**64 - 1)

    def uniform(self, lo, hi):
        self.s = (self.s + 0x9E3779B97F4A7C15) % 2**64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) % 2**64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) % 2**64
        z ^= z >> 31
        return lo + (hi - lo) * ((z >> 11) * (1.0 / 9007199254740992.0))


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

    def test_non_ascii_swept(self, core):
        # The input class the four interpreters provably disagreed on before
        # P2-12: multi-byte UTF-8, where a byte-count min() splits a codepoint.
        # rc_clamp_text_len is the codepoint-boundary-aware form; it must return
        # the same kept-byte count as contracts.clamp_text (now byte-canonical),
        # and — the safety property — never a length that lands mid-sequence.
        samples = ["héllo wörld", "café" * 8, "日本語のテキスト", "emoji😀🎉run",
                   "égalité", "a" * 30, "ünîcodé", "\U0001F600" * 6, ""]
        for s in samples:
            b = s.encode("utf-8")
            for max_len in (0, 1, 2, 3, 4, 5, 23, 24, 25, 64):
                py = len(contracts.clamp_text(s, max_len).encode("utf-8"))
                rs = core.rc_clamp_text_len(b, len(b), max_len)
                assert py == rs, (s, max_len, py, rs)
                # kept prefix is valid UTF-8 (never a split codepoint)
                b[:rs].decode("utf-8")


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

    def _run_schedule(self, core, fig, schedule, counters=(), render=False,
                      battery_level=100, seed=None):
        from dreamlayer.reality_compiler.v2 import Stage
        py = Stage(fig, rng=SplitMix(seed) if seed is not None else None,
                   battery_level=battery_level)
        rs = CoreStage(core, fig, battery_level=battery_level, seed=seed)
        try:
            for i, item in enumerate(schedule):
                kind, arg = item[0], item[1]
                if kind == "step":
                    py.step(arg)
                    rs.step(arg)
                else:
                    text = item[2] if len(item) > 2 else None
                    py.inject(arg, text) if text is not None else py.inject(arg)
                    rs.inject(arg, text)
                assert _py_state(py, counters) == rs.state(counters), (i, item)
                if render:
                    py_lines = [ln.text for ln in py.frame().lines]
                    assert py_lines == rs.render_lines(), (i, item)
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


class TestTextAndRenderParity:
    """The text path in the core: slot store, tokenized templates, and line
    rendering — checked frame-for-frame against the real Stage's frame()."""

    _run = TestStageStateMachineParity._run_schedule

    def test_rosetta_named_slots_render(self, core):
        # the migration pilot itself: the shipped Rosetta figment, fed named
        # slots, its three lines rendered by the core identically to frame()
        from dreamlayer.reality_compiler.v2 import native
        fig = native.rosetta_figment()
        schedule = [("inject", "text:langs", "ES → EN"),
                    ("inject", "text:translation", "hello, thanks"),
                    ("inject", "text:original", "hola, gracias"),
                    ("step", 0.05),
                    ("inject", "text:translation", "see you tomorrow"),
                    ("step", 1.0)]
        self._run(core, fig, schedule, render=True)

    def test_timer_countdown_renders_identically(self, core):
        # {remaining}/{elapsed} through ragged steps across the minute boundary
        from dreamlayer.reality_compiler.v2 import native
        fig = native.timer_figment(180)
        schedule = [("step", d) for d in (0.4, 11.6, 47.5, 59.7, 60.0, 5.3)]
        self._run(core, fig, schedule, render=True)

    def test_slot_cap_parity(self, core):
        # fill 'keep' first, overflow with new names: 'keep' survives on both,
        # and the rendered line agrees at every push
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, Transition, SELF, TextLine,
        )
        from dreamlayer.reality_compiler.v2.figment import MAX_SLOTS
        fig = Figment(name="cap", initial="a")
        a = fig.add_scene(Scene(id="a", lines=[TextLine("{slot:keep}", row=0)]))
        a.on["text"] = Transition(target=SELF)
        schedule = [("inject", "text:keep", "K")]
        schedule += [("inject", "text:x%d" % i, "v") for i in range(MAX_SLOTS + 4)]
        schedule += [("inject", "text:keep", "K2"), ("step", 0.05)]
        self._run(core, fig, schedule, render=True)

    def test_count_and_mixed_tokens_render(self, core):
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, CounterDecl, CounterOp, Transition, SELF, TextLine,
        )
        fig = Figment(name="mix", initial="a")
        fig.add_counter(CounterDecl("n", start=0, lo=0, hi=99))
        a = fig.add_scene(Scene(id="a", duration_sec=90.0, tick="countdown",
                                lines=[TextLine("n={count:n} t={remaining}", row=0),
                                       TextLine("{slot} {slot:tag}", row=1)],
                                on_timeout=[Transition(target=SELF)]))
        a.on["single"] = Transition(
            target=SELF, counter_ops=[CounterOp("n", "inc", 1)])
        a.on["text"] = Transition(target=SELF)
        schedule = ([("inject", "single")] * 3
                    + [("inject", "text", "dflt"), ("inject", "text:tag", "T"),
                       ("step", 33.3), ("inject", "single"), ("step", 66.6)])
        self._run(core, fig, schedule, counters=("n",), render=True)


class TestPeripheryParity:
    _run = TestStageStateMachineParity._run_schedule

    def test_battery_low_dispatch_and_cooldown(self, core):
        # level below the threshold: battery_low fires on the first advance,
        # then again only after the 60 s cooldown — counter tracked in lockstep
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, CounterDecl, CounterOp, Transition, SELF, TextLine,
        )
        fig = Figment(name="batt", initial="a")
        fig.battery_below = 30
        fig.add_counter(CounterDecl("warn", start=0, lo=0, hi=99))
        a = fig.add_scene(Scene(id="a", lines=[TextLine("{count:warn}", row=0)]))
        a.on["battery_low"] = Transition(
            target=SELF, counter_ops=[CounterOp("warn", "inc", 1)])
        schedule = [("step", d) for d in (1.0, 30.0, 30.5, 10.0, 55.0)]
        final = self._run(core, fig, schedule, counters=("warn",),
                          render=True, battery_level=20)
        assert final["counters"]["warn"] == 3    # t≈0, ≈61.5, ≈126.5

    def test_duration_range_trajectory_with_mirrored_rng(self, core):
        # a self-looping random-duration scene: the reference Stage rolls via
        # the mirrored SplitMix rng, the core via its own seeded stream —
        # identical rolls, identical trajectories, bit for bit
        from dreamlayer.reality_compiler.v2 import (
            Figment, Scene, Transition, SELF, TextLine,
        )
        fig = Figment(name="rng", initial="a")
        fig.add_scene(Scene(id="a", duration_range=(1.0, 3.0), tick="countup",
                            lines=[TextLine("{elapsed}", row=0)],
                            on_timeout=[Transition(target=SELF)]))
        schedule = [("step", 2.2)] * 8
        self._run(core, fig, schedule, render=True, seed=42)


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
