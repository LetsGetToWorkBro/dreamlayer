"""Differential testing: one generator, three interpreters, compared.

Instead of a fixed parity script over a fixed set of figments, Hypothesis
generates *valid* figments and random op scripts, and every one is run through
all three interpreters — Python (reference), JS (node/figment.js), and Lua
(lupa/figment_stage.lua) — with their traces compared. A divergence is
shrunk to a minimal figment automatically. This turns "the three interpreters
are bit-for-bit identical" from a hand-maintained promise into a machine-checked
property.

JS↔Py are compared on the *full* frame trace (both emit the rich snapshot);
Lua is compared on the core observable (scene / ended / drawn lines / counters)
at the end of each generated script, adding the third engine over generated
input. Requires node + lupa; skipped where either is absent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("hypothesis")
lupa = pytest.importorskip("lupa")
if not shutil.which("node"):
    pytest.skip("node not installed", allow_module_level=True)

from hypothesis import given, settings, strategies as st, assume, HealthCheck

from dreamlayer.reality_compiler.v2 import figment as F, transport
from dreamlayer.reality_compiler.v2.budgets import verify
from dreamlayer.reality_compiler.v2.interpreter import Stage

LENS = Path(__file__).resolve().parents[4] / "landing" / "assets" / "lens"
HALO_LUA = Path(__file__).resolve().parents[4] / "halo-lua"

COLORS = sorted(F.COLOR_TOKENS)
SIZES = sorted(F.SIZES)
BASE_CONTENTS = ["HELLO", "{remaining}", "{elapsed}", "{slot}", "wait"]
EVENTS = ["single", "double", "long", "imu_tap", "text"]


# ---------------------------------------------------------------------------
# Generate a *valid* figment (constructed to pass, filtered by verify())
# ---------------------------------------------------------------------------

@st.composite
def figments(draw):
    n = draw(st.integers(min_value=1, max_value=4))
    ids = [f"s{i}" for i in range(n)]
    fig = F.Figment(name="gen", initial="s0")
    n_ctr = draw(st.integers(min_value=0, max_value=1))
    for i in range(n_ctr):
        fig.add_counter(F.CounterDecl(f"c{i}", start=draw(st.integers(0, 3)),
                                      lo=0, hi=9))
    # only reference count tokens for counters that actually exist — the builder
    # never emits an undeclared {count:cN} (that's a separate, out-of-grammar case)
    contents = BASE_CONTENTS + [f"{{count:c{i}}}" for i in range(n_ctr)]

    def target(draw):
        return draw(st.sampled_from(ids + [F.END, F.SELF]))

    def lines(draw):
        rows = draw(st.lists(st.integers(0, 4), min_size=0, max_size=3,
                             unique=True))
        return [F.TextLine(draw(st.sampled_from(contents)), row=r,
                           size=draw(st.sampled_from(SIZES)),
                           color=draw(st.sampled_from(COLORS))) for r in rows]

    def events(draw):
        on = {}
        for ev in draw(st.lists(st.sampled_from(EVENTS), max_size=3, unique=True)):
            t = F.Transition(target=target(draw))
            if draw(st.booleans()):
                t.emit = "tap"                 # event emits don't affect flood
            on[ev] = t
        return on

    for sid in ids:
        timed = draw(st.booleans())
        if timed:
            dur = draw(st.integers(1, 5)) * 1.0
            tick = draw(st.sampled_from([None, "countdown"]))
            fig.add_scene(F.Scene(
                id=sid, lines=lines(draw), duration_sec=dur, tick=tick,
                on_timeout=[F.Transition(target=target(draw))],
                on=events(draw)))
        else:
            fig.add_scene(F.Scene(id=sid, lines=lines(draw), on=events(draw)))

    assume(verify(fig).ok)                     # only run genuinely valid figments
    return fig


@st.composite
def scripts(draw):
    ops = []
    for _ in range(draw(st.integers(1, 6))):
        if draw(st.booleans()):
            ops.append(["step", draw(st.integers(1, 6)) * 1.0])
        else:
            ev = draw(st.sampled_from(EVENTS))
            ops.append(["inject", ev, "HI"] if ev == "text" else ["inject", ev])
    ops.append(["step", draw(st.integers(1, 4)) * 1.0])   # end on a render
    return ops


# ---------------------------------------------------------------------------
# Three interpreters, one comparable trace
# ---------------------------------------------------------------------------

def _py_trace(fig, script):
    stg = Stage(fig)

    def snap():
        fr = stg.frame()
        return {"scene": "@end" if stg.ended else stg.current, "ended": stg.ended,
                "lines": [ln.text for ln in fr.lines],
                "remaining": round(stg.remaining(), 3), "pulse": fr.pulse_on,
                "cadence_phase": fr.cadence_phase,
                "cadence_level": round(fr.cadence_level, 3),
                "counters": dict(stg.counters)}
    trace = [snap()]
    for op in script:
        if op[0] == "step":
            stg.step(op[1])
        else:
            stg.inject(op[1], op[2] if len(op) > 2 else None)
        trace.append(snap())
    return trace


def _js_trace(fig, script):
    out = subprocess.run(["node", "stage_probe.js"], cwd=LENS,
                         input=json.dumps({"fig": fig.to_dict(), "script": script}),
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _lua_final(rt, fig, script):
    stage = rt["stage"]
    put = transport.put_envelope(fig)
    swap = transport.swap_envelope(fig.id)
    rt["deliver"](rt["decode"](json.dumps(put)))
    rt["deliver"](rt["decode"](json.dumps(swap)))
    for op in script:
        if op[0] == "step":
            stage.tick(op[1])
        elif op[1] == "text":
            stage.on_event("text", op[2] if len(op) > 2 else "")
        else:
            stage.on_event(op[1])
    stv, active = stage._state()
    counters = {}
    if stv is not None and stv.counters is not None:
        for k in stv.counters:
            counters[k] = stv.counters[k]
    ended = bool(stv.ended) if stv is not None else True
    scene = "@end" if ended else (stv.current if stv is not None else "@end")
    # lupa tables iterate as keys; take the values for the drawn line strings
    lines = list(rt["lines"]().values()) if not ended else []
    return {"scene": scene, "ended": ended, "lines": lines, "counters": counters}


LUA_RUNNER = '''
local stage = require("app.figment_stage")
local drawn, handlers = {}, {}
stage.bind({ display = {
    text  = function(s) drawn[#drawn+1] = s end,
    clear = function() drawn = {} end, show = function() _G.__shown = drawn end,
  }, send = function() end, battery = function() return 100 end,
  random = function() return 0.5 end })
stage.register({ register = function(t, fn) handlers[t] = fn end })
return {
  stage = stage,
  decode = function(s) return require("lib.json").decode(s) end,
  deliver = function(msg) handlers[msg.t](msg) end,
  lines = function() local o={} for i,s in ipairs(_G.__shown or {}) do o[i]=s end return o end,
}
'''


@pytest.fixture
def lua_rt():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{HALO_LUA}/?.lua;" .. package.path')
    return rt.execute(LUA_RUNNER)


def _final_observable(snap):
    return {"scene": snap["scene"], "ended": snap["ended"],
            "lines": snap["lines"], "counters": snap["counters"]}


class TestDifferential:
    @settings(max_examples=30, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture,
                                     HealthCheck.too_slow])
    @given(fig=figments(), script=scripts())
    def test_three_interpreters_agree(self, lua_rt, fig, script):
        py = _py_trace(fig, script)
        js = _js_trace(fig, script)
        # JS ↔ Py: the full per-step frame trace must match exactly
        assert len(js) == len(py)
        for i, (a, b) in enumerate(zip(js, py)):
            a = {**a, "remaining": round(a["remaining"], 3)}
            assert a == b, f"JS↔Py diverged at step {i}: {a} != {b}"
        # Lua ↔ Py: the core observable at the end of the script must match
        lua = _lua_final(lua_rt, fig, script)
        assert lua == _final_observable(py[-1]), \
            f"Lua↔Py final diverged: {lua} != {_final_observable(py[-1])}"
