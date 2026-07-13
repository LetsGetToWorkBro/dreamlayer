"""P2-12: one canonical text-length unit, proven byte-identical across all four
interpreters on the input class they used to disagree on.

Before this, the four figment interpreters clamped a display line by four
different units — Python code points, JS UTF-16 units, Lua and Rust bytes — so
a host-pushed non-ASCII slot value rendered to a different string on each, and a
naive byte-cut could split a UTF-8 codepoint (making the Rust core emit invalid
UTF-8 and the parity harness raise instead of diff). The canonical unit is now
**UTF-8 bytes, truncated on a codepoint boundary**, everywhere.

These vectors are hardcoded (the strongest, least-flaky parity anchor): each is
pushed into a real ``{slot}`` line and rendered through every interpreter that
is installed — Python always; Rust via ctypes; JS via node; Lua via lupa — and
the rendered bytes must match Python's exactly. Missing engines skip, never
fail, so the test tightens as toolchains appear rather than rotting.
"""
from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dreamlayer.reality_compiler.v2 import figment as F, transport
from dreamlayer.reality_compiler.v2.interpreter import Stage
from dreamlayer.reality_compiler.v2.figment import MAX_TEXT_LEN

LENS = Path(__file__).resolve().parents[4] / "landing" / "assets" / "lens"
HALO_LUA = Path(__file__).resolve().parents[4] / "halo-lua"
CRATE = Path(__file__).resolve().parents[4] / "reality-core"

# The input classes P2-12 names: non-ASCII (2/3/4-byte sequences, incl. astral
# emoji as surrogate pairs) and token-in-slot (a value that looks like a token
# but is inert data). Several exceed MAX_TEXT_LEN to exercise the boundary clamp.
VECTORS = [
    "HI",
    "héllo wörld ünîcodé",
    "日本語のテキスト表示です",
    "emoji 😀🎉🚀 run here",
    "{slot}{count:c0}{remaining}",
    "égalité, fraternité",
    "x" * 40,
    "café" * 9,
    "日" * 20,
    "a😀b日c",
    "",
]


# ---------------------------------------------------------------------------
# The reference: Python renders "{slot}" with the pushed value.
# ---------------------------------------------------------------------------

def _figment():
    fig = F.Figment(name="clamp", initial="s0")
    fig.add_scene(F.Scene(id="s0", lines=[F.TextLine("{slot}", row=0)]))
    return fig


def _py_render(value: str) -> str:
    stg = Stage(_figment())
    stg.inject("text", value)
    return stg.frame().lines[0].text


def test_python_reference_is_byte_canonical():
    # The reference itself obeys the canonical unit: never more than MAX_TEXT_LEN
    # UTF-8 bytes, and never a split codepoint (decodes cleanly).
    for v in VECTORS:
        out = _py_render(v)
        assert len(out.encode("utf-8")) <= MAX_TEXT_LEN
        out.encode("utf-8").decode("utf-8")             # valid UTF-8


# ---------------------------------------------------------------------------
# Rust core (ctypes): rc_clamp_text_len is the codepoint-boundary byte clamp.
# ---------------------------------------------------------------------------

def _load_rust():
    for name in ("libreality_core.so", "libreality_core.dylib", "reality_core.dll"):
        for base in (CRATE / "target" / "release", CRATE / "target" / "debug"):
            p = base / name
            if p.exists():
                return ctypes.CDLL(str(p))
    if not shutil.which("cargo"):
        return None
    out = subprocess.run(["cargo", "build", "--release"], cwd=CRATE,
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return _load_rust()


def test_rust_core_matches_python():
    lib = _load_rust()
    if lib is None:
        pytest.skip("reality-core dylib/cargo not available")
    lib.rc_clamp_text_len.restype = ctypes.c_uint64
    lib.rc_clamp_text_len.argtypes = [ctypes.c_char_p, ctypes.c_uint64,
                                      ctypes.c_uint64]
    for v in VECTORS:
        b = v.encode("utf-8")
        kept = lib.rc_clamp_text_len(b, len(b), MAX_TEXT_LEN)
        # Rust keeps the same byte count the Python reference does, on a boundary
        assert kept == len(_py_render(v).encode("utf-8")), v
        assert b[:kept].decode("utf-8") == _py_render(v), v


# ---------------------------------------------------------------------------
# JS (node): the real Stage renders "{slot}" through figment.js.
# ---------------------------------------------------------------------------

def test_js_matches_python():
    if not shutil.which("node") or not (LENS / "stage_probe.js").exists():
        pytest.skip("node / stage_probe.js not available")
    fig = _figment().to_dict()
    for v in VECTORS:
        script = [["inject", "text", v], ["step", 0.0]]
        out = subprocess.run(["node", "stage_probe.js"], cwd=LENS,
                             input=json.dumps({"fig": fig, "script": script}),
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        trace = json.loads(out.stdout)
        js_line = (trace[-1]["lines"] or [""])[0]
        assert js_line == _py_render(v), (v, js_line, _py_render(v))


# ---------------------------------------------------------------------------
# Lua (lupa): the real figment_stage renders "{slot}" on-glass.
# ---------------------------------------------------------------------------

_LUA_RUNNER = '''
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


def test_lua_matches_python():
    lupa = pytest.importorskip("lupa")
    fig = _figment()
    for v in VECTORS:
        # default utf-8 encoding: boundary-safe clamping guarantees the rendered
        # bytes are valid UTF-8, so lupa hands back a clean Python str.
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute('package.path = "%s/?.lua;" .. package.path' % HALO_LUA)
        env = rt.execute(_LUA_RUNNER)
        env["deliver"](env["decode"](json.dumps(transport.put_envelope(fig))))
        env["deliver"](env["decode"](json.dumps(transport.swap_envelope(fig.id))))
        env["stage"].on_event("text", v)
        env["stage"].tick(0.0)
        vals = list(env["lines"]().values())
        lua_line = vals[0] if vals else ""
        assert lua_line == _py_render(v), (v, lua_line, _py_render(v))
