"""Tests for display/horizon.lua — the Meridian rim instrument
(docs/cinema_v2/horizon.md, horizon_frame.md).

Covers the frame codec (validation, seq guard, malformed-frame
retention), the pause contract, staleness tier-drop, the mark cap, and
reduce_motion parity of the notch. Lua driven via lupa (test_transitions
pattern) with a recording frame stub.
"""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"

ACCENT_MEMORY     = 0x2CC79A
ACCENT_MEMORY_DIM = 0x1A7A60
STATUS_PAUSED     = 0x8FA8B2


def _make_runtime():
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _calls = {}
    frame = { display = {
      line   = function(...) _calls[#_calls+1] = {"line", ...} end,
      rect   = function(...) _calls[#_calls+1] = {"rect", ...} end,
      circle = function(...) _calls[#_calls+1] = {"circle", ...} end,
      text   = function(...) _calls[#_calls+1] = {"text", ...} end,
      bitmap = function(...) end,
      clear  = function(...) end,
      show   = function(...) end,
      assign_color_ycbcr = function(...) end,
    }}
    """)
    return rt


@pytest.fixture()
def hz():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = _make_runtime()
    rt.execute('_hz = require("display.horizon")')
    rt.execute('_a  = require("display.animations")')
    rt.execute("_hz.reset()")
    return rt


def _color_counts(rt):
    counts = rt.eval("""
      (function()
        local counts = {}
        for _, c in ipairs(_calls) do
          local col = c[#c]
          if type(col) == "boolean" then col = c[#c - 1] end
          counts[col] = (counts[col] or 0) + 1
        end
        return counts
      end)()
    """)
    return {int(k): int(v) for k, v in counts.items()}


DAY = "{ t='horizon', seq=1, paused=0, v={ 0,102, 450,101, -1350,222 } }"


# ---------------------------------------------------------------------------
# Frame codec
# ---------------------------------------------------------------------------

def test_valid_frame_parses_marks(hz):
    assert hz.eval(f"_hz.on_frame({DAY}, 1000)")
    marks = hz.eval("_hz.marks()")
    assert len(marks) == 3
    assert marks[1].deg == 0 and marks[1].kind == 1 and marks[1].luma == 2
    assert marks[3].kind == 2 and marks[3].state == 2   # healthy promise


def test_stale_seq_dropped(hz):
    hz.eval(f"_hz.on_frame({DAY}, 1000)")
    assert not hz.eval(
        "_hz.on_frame({ t='horizon', seq=1, paused=0, v={} }, 2000)")
    assert len(hz.eval("_hz.marks()")) == 3   # previous day retained


def test_malformed_frames_keep_previous_day(hz):
    hz.eval(f"_hz.on_frame({DAY}, 1000)")
    # odd arity
    assert not hz.eval(
        "_hz.on_frame({ t='horizon', seq=2, v={ 100 } }, 2000)")
    # unknown kind code (kind 9)
    assert not hz.eval(
        "_hz.on_frame({ t='horizon', seq=3, v={ 100, 902 } }, 2000)")
    # non-numeric entry
    assert not hz.eval(
        "_hz.on_frame({ t='horizon', seq=4, v={ 100, 'x' } }, 2000)")
    assert len(hz.eval("_hz.marks()")) == 3   # a parse error never blanks


def test_marks_capped_at_max(hz):
    hz.execute("""
      local v = {}
      for i = 1, 60 do v[#v+1] = i * 10; v[#v+1] = 101 end
      _hz.on_frame({ t='horizon', seq=1, v = v }, 1000)
    """)
    assert len(hz.eval("_hz.marks()")) == hz.eval("_a.MER_MARKS_MAX")


# ---------------------------------------------------------------------------
# Pause contract: no marks while paused, notch flips token
# ---------------------------------------------------------------------------

def test_paused_frame_draws_notch_only(hz):
    hz.eval(f"_hz.on_frame({DAY}, 1000)")
    hz.eval("_hz.on_frame({ t='horizon', seq=2, paused=1, v={} }, 1100)")
    assert hz.eval("_hz.is_paused()")
    hz.execute("_calls = {}; _hz.draw({ now_ms = 1200 })")
    counts = _color_counts(hz)
    assert counts[STATUS_PAUSED]            # the paused notch
    assert ACCENT_MEMORY not in counts      # no marks, no live notch
    assert ACCENT_MEMORY_DIM not in counts


def test_paused_state_even_with_marks_in_same_frame(hz):
    # defense in depth: a (buggy) paused frame carrying marks draws none
    hz.eval("_hz.on_frame({ t='horizon', seq=1, paused=1, v={ 0,102 } }, 1000)")
    hz.execute("_calls = {}; _hz.draw({ now_ms = 1100 })")
    counts = _color_counts(hz)
    assert ACCENT_MEMORY not in counts


# ---------------------------------------------------------------------------
# Staleness: marks drop one luma tier after MER_STALE_MS; notch unaffected
# ---------------------------------------------------------------------------

def test_stale_link_drops_mark_tier(hz):
    hz.eval("_hz.on_frame({ t='horizon', seq=1, v={ 0,102 } }, 1000)")
    hz.execute("_calls = {}; _hz.draw({ now_ms = 2000 })")
    fresh = _color_counts(hz)
    hz.execute("_calls = {}; _hz.draw({ now_ms = 1000 + _a.MER_STALE_MS + 1000 })")
    stale = _color_counts(hz)
    # fresh: full-tier mark lines exceed stale's; the dim token gains them
    assert fresh.get(ACCENT_MEMORY, 0) > stale.get(ACCENT_MEMORY, 0)
    assert stale.get(ACCENT_MEMORY_DIM, 0) > fresh.get(ACCENT_MEMORY_DIM, 0)


# ---------------------------------------------------------------------------
# Notch: breathing vs reduce_motion static — information preserved
# ---------------------------------------------------------------------------

def _notch_lines(rt, now, reduce):
    rt.execute(
        f"_calls = {{}}; _hz.draw({{ now_ms = {now}, "
        f"reduce_motion = {'true' if reduce else 'false'} }})")
    lines = rt.eval("""
      (function()
        local out = {}
        for _, c in ipairs(_calls) do
          if c[1] == "line" then out[#out+1] = { c[2], c[3], c[4], c[5] } end
        end
        return out
      end)()
    """)
    return [tuple(int(v) for v in line.values()) for line in lines.values()]


def test_notch_breathes_with_time_but_not_under_reduce_motion(hz):
    hz.eval("_hz.on_frame({ t='horizon', seq=1, v={} }, 0)")
    a = _notch_lines(hz, 400, False)
    b = _notch_lines(hz, 1600, False)
    assert a != b                                    # geometric breathe
    ra = _notch_lines(hz, 400, True)
    rb = _notch_lines(hz, 1600, True)
    assert ra == rb                                  # static, info preserved


# ---------------------------------------------------------------------------
# Highlight / arrival pulse expire on their clocks
# ---------------------------------------------------------------------------

def test_highlight_and_pulse_expire(hz):
    hz.eval("_hz.on_frame({ t='horizon', seq=1, v={} }, 1000)")
    hz.execute("_hz.set_highlight(30, 1000)")
    hz.execute("_calls = {}; _hz.draw({ now_ms = 1100 })")
    lit = _color_counts(hz).get(ACCENT_MEMORY, 0)
    assert lit > 0   # highlight draws a full-tier mark (plus the notch)
    hz.execute("_calls = {}; _hz.draw({ now_ms = 1000 + _a.MER_HIGHLIGHT_MS + 100 })")
    after = _color_counts(hz).get(ACCENT_MEMORY, 0)
    assert after < lit   # highlight gone; only the notch remains
