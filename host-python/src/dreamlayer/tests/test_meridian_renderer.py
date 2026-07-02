"""Integration tests for the Meridian render loop
(display/renderer.lua + focus.lua + horizon.lua on a controlled clock):
the idle horizon, the focus law's phases, the privacy no-residue
contract, reduce_motion parity, the testimony thread, timing budgets,
and the layout-driven cards that v1 queued but never drew.
"""
import pathlib

import pytest

try:
    from lupa import lua53
    LUPA_AVAILABLE = True
except ImportError:
    LUPA_AVAILABLE = False

LUA_ROOT = pathlib.Path(__file__).parents[4] / "halo-lua"

ACCENT_MEMORY = 0x2CC79A
CX = CY = 128

OBJECT_CARD = """{
  type = "ObjectRecallCard", object = "KEYS", primary = "Keys",
  place = "Kitchen table", detail = "beside blue notebook",
  last_seen = "7:42 PM", confidence = 0.9, origin_deg = 0,
}"""

PRIVACY_CARD = '{ type = "PrivacyPausedCard" }'

TRUTH_CARD = """{
  type = "TruthLensCard", verdict = "ELEVATED", confidence = 0.7,
  stages = {
    { confidence = 0.8, direction = "truthful" },
    { confidence = 0.6, direction = "deceptive" },
    { confidence = 0.0, direction = "insufficient" },
    { confidence = 0.7, direction = "truthful" },
    { confidence = 0.5, direction = "truthful" },
    { confidence = 0.9, direction = "deceptive" },
    { confidence = 0.4, direction = "truthful" },
    { confidence = 0.6, direction = "truthful" },
    { confidence = 0.7, direction = "truthful" },
  } }"""

CONSENT_CARD = """{
  type = "ConsentRequiredCard", eyebrow = "CONSENT REQUIRED",
  primary = "Allow access?", detail = "Calendar access",
  footer = "Hold to allow", layout = {
    eyebrow = { x = 128, y = 64 }, primary = { x = 128, y = 112 },
    separator = { x1 = 48, x2 = 208, y = 80 },
    lock = { x = 128, y = 40, r = 10 },
  } }"""


@pytest.fixture()
def dev():
    if not LUPA_AVAILABLE:
        pytest.skip("lupa not installed")
    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _calls, _shows, __now = {}, 0, 0
    frame = { display = {
      line   = function(...) _calls[#_calls+1] = {"line", ...} end,
      rect   = function(...) _calls[#_calls+1] = {"rect", ...} end,
      circle = function(...) _calls[#_calls+1] = {"circle", ...} end,
      text   = function(...) _calls[#_calls+1] = {"text", ...} end,
      bitmap = function(...) end,
      clear  = function(...) _calls = {} end,
      show   = function(...) _shows = _shows + 1 end,
      assign_color_ycbcr = function(...) end,
    }}
    """)
    rt.execute('_r  = require("display.renderer")')
    rt.execute('_hz = require("display.horizon")')
    rt.execute('_a  = require("display.animations")')
    rt.execute('_tr = require("display.transitions")')
    rt.execute("_r.bind(nil, function() return __now end)")
    rt.execute("_hz._now_ms = function() return __now end")
    rt.execute("_hz.reset(); _tr.set_reduce_motion(false)")
    rt.execute("_hz.on_frame({ t='horizon', seq=1, v={ 0,102, -1350,222 } }, 0)")
    return rt


def _texts(rt):
    return rt.eval("""
      (function()
        local out = {}
        for _, c in ipairs(_calls) do
          if c[1] == "text" then out[#out+1] = tostring(c[2]) end
        end
        return table.concat(out, "|")
      end)()
    """)


def _n_calls(rt, kind):
    return rt.eval(f"""
      (function()
        local n = 0
        for _, c in ipairs(_calls) do if c[1] == "{kind}" then n = n + 1 end end
        return n
      end)()
    """)


def _has_line_at_radius(rt, r, tol=2.5):
    return rt.eval(f"""
      (function()
        for _, c in ipairs(_calls) do
          if c[1] == "line" then
            local dx1, dy1 = c[2] - {CX}, c[3] - {CY}
            local dx2, dy2 = c[4] - {CX}, c[5] - {CY}
            local r1 = math.sqrt(dx1*dx1 + dy1*dy1)
            local r2 = math.sqrt(dx2*dx2 + dy2*dy2)
            if math.abs(r1 - {r}) < {tol} and math.abs(r2 - {r}) < {tol} then
              return true
            end
          end
        end
        return false
      end)()
    """)


# ---------------------------------------------------------------------------
# The resting display is the day, never a black screen
# ---------------------------------------------------------------------------

def test_idle_tick_draws_the_horizon(dev):
    dev.execute("__now = 1000; _r.tick()")
    assert _n_calls(dev, "line") > 0        # track + marks + notch
    assert dev.eval("_shows") == 1


# ---------------------------------------------------------------------------
# Focus law phases
# ---------------------------------------------------------------------------

def test_travel_phase_shows_no_content(dev):
    dev.execute(f"__now = 1000; _r.show_card({OBJECT_CARD})")
    dev.execute("__now = 1080; _r.tick()")   # mid-travel (80 < 140)
    assert "Kitchen table" not in _texts(dev)
    assert _n_calls(dev, "circle") >= 1      # the head is flying


def test_hold_shows_content_and_confidence_ring(dev):
    dev.execute(f"__now = 1000; _r.show_card({OBJECT_CARD})")
    dev.execute("__now = 1400; _r.tick()")   # past enter (240ms)
    assert "Kitchen table" in _texts(dev)
    assert _has_line_at_radius(dev, dev.eval("_a.SIG_FOCUS_RING_R"))


def test_recede_cuts_text_after_the_cut_fraction(dev):
    dev.execute(f"__now = 1000; _r.show_card({OBJECT_CARD})")
    dev.execute("__now = 1400; _r.tick()")
    dev.execute("_r.dismiss()")
    dev.execute("__now = 1400 + 100; _r.tick()")   # t=0.63 > 0.4
    assert "Kitchen table" not in _texts(dev)


def test_recede_completion_returns_to_horizon_with_pulse(dev):
    dev.execute(f"__now = 1000; _r.show_card({OBJECT_CARD})")
    dev.execute("__now = 1400; _r.tick()")
    dev.execute("_r.dismiss()")
    dev.execute("__now = 1400 + 200; _r.tick()")   # past SIG_RECEDE_MS
    # back to idle horizon; the origin mark pulses at full tier
    assert "Kitchen" not in _texts(dev)
    assert _n_calls(dev, "line") > 0


# ---------------------------------------------------------------------------
# Privacy class: slam in, hard cut out, no residue
# ---------------------------------------------------------------------------

def test_privacy_card_recede_has_no_flight(dev):
    dev.execute(f"__now = 1000; _r.show_card({PRIVACY_CARD})")
    dev.execute("__now = 1300; _r.tick()")
    dev.execute("_r.dismiss()")
    dev.execute("__now = 1380; _r.tick()")   # mid-recede
    # no focus-flight circles for privacy-class cards (shield geometry
    # contracts, but nothing flies to the rim)
    heads = dev.eval("""
      (function()
        local n = 0
        for _, c in ipairs(_calls) do
          if c[1] == "circle" and c[5] == true and (c[4] == 2 or c[4] == 3) then
            n = n + 1
          end
        end
        return n
      end)()
    """)
    assert heads == 0


# ---------------------------------------------------------------------------
# reduce_motion parity: full information on the first frame
# ---------------------------------------------------------------------------

def test_reduce_motion_holds_immediately_with_ring_and_origin_tick(dev):
    dev.execute('require("system.settings").set("reduce_motion", true)')
    dev.execute(f"__now = 1000; _r.show_card({OBJECT_CARD})")
    dev.execute("__now = 1050; _r.tick()")
    assert "Kitchen table" in _texts(dev)    # content complete at once
    assert _has_line_at_radius(dev, dev.eval("_a.SIG_FOCUS_RING_R"))
    dev.execute('require("system.settings").set("reduce_motion", false)')


# ---------------------------------------------------------------------------
# Testimony thread
# ---------------------------------------------------------------------------

def test_testimony_settles_with_thread_and_no_focus_ring(dev):
    dev.execute(f"__now = 1000; _r.show_card({TRUTH_CARD})")
    dev.execute("__now = 1000 + 400 + 720 + 100; _r.tick()")
    assert "ELEVATED" in _texts(dev)
    assert _has_line_at_radius(dev, dev.eval("_a.TESTIMONY_R"), tol=4.5)
    # the thread is the card's confidence surface: no ring at r=92
    assert not _has_line_at_radius(dev, dev.eval("_a.SIG_FOCUS_RING_R"), tol=1.5)


def test_testimony_accumulates_in_stage_order(dev):
    dev.execute(f"__now = 1000; _r.show_card({TRUTH_CARD})")
    dev.execute("__now = 1000 + 400 + 160; _r.tick()")   # 2 stages in
    early = _n_calls(dev, "line")
    dev.execute("__now = 1000 + 400 + 700; _r.tick()")   # nearly all
    late = _n_calls(dev, "line")
    assert late > early


# ---------------------------------------------------------------------------
# Layout-driven cards: v1 queued these and drew NOTHING
# ---------------------------------------------------------------------------

def test_consent_card_actually_draws(dev):
    dev.execute(f"__now = 1000; _r.show_card({CONSENT_CARD})")
    dev.execute("__now = 1400; _r.tick()")
    texts = _texts(dev)
    assert "Allow access?" in texts and "CONSENT REQUIRED" in texts


# ---------------------------------------------------------------------------
# Timing budgets (the hardware envelope, asserted)
# ---------------------------------------------------------------------------

def test_focus_enter_fits_the_reactive_budget(dev):
    # sensor-to-first-frame P95 budget is 500ms for reactive elements;
    # the full condensation must leave headroom for BLE + host time
    assert dev.eval("_a.SIG_FOCUS_TRAVEL_MS + _a.SIG_FOCUS_LAND_MS") <= 300
    assert dev.eval("_a.SIG_RECEDE_MS") <= 200


def test_testimony_enter_bounded(dev):
    total = dev.eval("_a.SIG_RIPPLE_MS + 9 * _a.TESTIMONY_STAGE_MS")
    assert total <= 1200   # a verdict never makes the wearer wait


def test_horizon_frame_cadence_is_ambient(dev):
    # the dial is ambient (≈3s budget class); constants must agree
    assert dev.eval("_a.MER_STALE_MS") >= 10000
    assert dev.eval("_a.MER_ARRIVAL_PULSE_MS") <= 500


def test_dial_geometry_is_consistent(dev):
    # seam edges must equal the window caps: ±(window × deg/hour) from now
    window_deg = dev.eval("_a.MER_WINDOW_HOURS * _a.MER_DEG_PER_HOUR")
    assert dev.eval("_a.MER_SEAM_FROM_DEG") == -90 + window_deg
    assert dev.eval("_a.MER_SEAM_TO_DEG") == pytest.approx(-90 - window_deg + 360)
