--- display/transitions.lua
--- Meridian (Cinema v2) survivors of the Halo Cinema v1 signature set:
---   S2 ghost_wake_text  WorldAnchor echo — Perlin condensation (kept)
---   S5 truth_ripple     Truth Lens verdict ENTER — ripple from eye landmark
---   chime / chord / rumble  HUD acoustics analogs (kept)
---   exit_contract       geometry contracts, text cuts at t=0.4 (kept rule)
---
--- Killed in v2 with replacements shipping in the same PR (see
--- docs/CINEMA_V2_DELTAS.md §1-§4): iris_bloom and confidence_halo are
--- unified into the Focus law's landing/hold ring (display/focus.lua),
--- prism_slide is replaced by recede+condense overlap, and memory_comet
--- is generalized into condensation travel from the horizon angle.
---
--- Every timing constant comes from display/animations.lua. Every color
--- is a palette token. Every signature honors reduce_motion via
--- transitions.set_reduce_motion(); display/focus.lua reads the same flag.
---
--- Public API:
---   transitions.set_reduce_motion(flag) / transitions.reduce_motion()
---   transitions.enter_duration(sig_name)  -> ms
---   transitions.ghost_wake_text(x, y, text, size, t, seed_ms)
---   transitions.truth_ripple(t, ox, oy)
---   transitions.truth_ripple_cold(t, ox, oy)
---   transitions.chime(t, cx, cy)
---   transitions.chord(t, cx, cy, confidence)
---   transitions.rumble(t)
---   transitions.exit_contract(t)          -> scale, text_visible

local math = math
local A    = require("display.animations")
local P    = require("display.palette")
local E    = require("lib.easing")
local MAT  = require("display.materials")

local HAS_FRAME = (type(_G.frame) == "table")

local transitions = {}

local CX, CY = 128, 128

local _reduce_motion = false

function transitions.set_reduce_motion(flag)
  _reduce_motion = not not flag
end

function transitions.reduce_motion()
  return _reduce_motion
end

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------
local function floor(n) return math.floor(n + 0.5) end
local function clamp(v, lo, hi) return math.max(lo, math.min(hi, v)) end
local function lerp(a, b, t) return a + (b - a) * t end

local function arc(cx, cy, r, a0, a1, color, steps)
  if not HAS_FRAME or r <= 0 then return end
  steps = steps or 32
  local sweep = a1 - a0
  local function pt(deg)
    local rd = math.rad(deg)
    return cx + r * math.cos(rd), cy + r * math.sin(rd)
  end
  local x0, y0 = pt(a0)
  for i = 1, steps do
    local x1, y1 = pt(a0 + sweep * i / steps)
    frame.display.line(floor(x0), floor(y0), floor(x1), floor(y1), color)
    x0, y0 = x1, y1
  end
end

-- ---------------------------------------------------------------------------
-- Per-signature enter durations (renderer's phase clock reads these)
-- ---------------------------------------------------------------------------
local ENTER_MS = {
  ghost_wake = A.SIG_GHOSTWAKE_MS,
  ripple     = A.SIG_RIPPLE_MS,
}

function transitions.enter_duration(sig)
  if _reduce_motion then return 0 end
  return ENTER_MS[sig] or A.ENTER_DURATION_MS
end

-- ---------------------------------------------------------------------------
-- S2 Ghost Wake
-- Per-character Perlin jitter converging over 320ms while the ghost slot
-- luma ramps 0 -> ghost. Character x-advance approximates typography "sm".
-- ---------------------------------------------------------------------------
local GHOSTWAKE_CHAR_W = 10   -- matches typography AVG_W.sm

-- UTF-8 aware character split. v1 iterated BYTES (text:sub(i,i)), which
-- sliced multi-byte glyphs — the "• MEMORY ECHO •" bullets the anchor
-- renderer actually sends became three garbage draws per bullet on
-- device. Found by the Meridian raster harness (Phase 5 golden pass).
local function utf8_chars(s)
  local chars = {}
  for ch in s:gmatch("[%z\x01-\x7F\xC2-\xFD][\x80-\xBF]*") do
    chars[#chars + 1] = ch
  end
  return chars
end

function transitions.ghost_wake_text(x, y, text, size, t, seed_ms)
  MAT.init()
  text = tostring(text)
  if _reduce_motion or t >= 1 then
    MAT.draw_ghost_text(x, y, text, size, 1.0)
    return
  end
  t = clamp(t, 0, 1)
  P.set_dynamic_y("ghost_text",
                  lerp(A.SIG_GHOSTWAKE_Y_FROM, A.SIG_GHOSTWAKE_Y_TO, t))
  if not HAS_FRAME then return end
  -- Solid: ghost glyphs render at their token size explicitly (no
  -- sticky-font bleed from whatever card drew last)
  require("display.primitives").set_font_size(size or "sm")
  local amp   = A.SIG_GHOSTWAKE_JITTER_PX * (1 - E.in_out_cubic(t))
  local seed  = (seed_ms or 0) * 0.004
  local color = P.dynamic_color("ghost_text")
  local chars = utf8_chars(text)
  local n     = #chars
  local x0    = x - floor(n * GHOSTWAKE_CHAR_W / 2)
  for i = 1, n do
    local ch = chars[i]
    if ch ~= " " then
      local jx = E.perlin1d(seed + i * 7.13)  * amp
      local jy = E.perlin1d(seed + i * 13.7 + 51) * amp
      frame.display.text(ch, floor(x0 + (i - 1) * GHOSTWAKE_CHAR_W + jx),
                         floor(y + jy), color)
    end
  end
end

-- ---------------------------------------------------------------------------
-- S5 Truth Ripple
-- Ripple pair expanding from the eye landmark with a warm palette pulse on
-- the fx slot. Cold variant for false-positive dismiss.
-- ---------------------------------------------------------------------------
local function ripple(t, ox, oy, dcb, dcr)
  MAT.init()
  if _reduce_motion then
    P.restore("fx")
    return
  end
  t = clamp(t, 0, 1)
  ox, oy = ox or CX, oy or 96
  -- chroma pulse peaks at t=0.33 then decays
  local pulse = (t < 0.33) and (t / 0.33) or (1 - (t - 0.33) / 0.67)
  P.shift_dynamic("fx", 0, dcb * pulse, dcr * pulse)
  if t < 1 then
    local r = E.out_quad(t) * A.SIG_RIPPLE_R_MAX
    arc(ox, oy, floor(r),      0, 360, P.dynamic_color("fx"), 28)
    if r > 12 then
      arc(ox, oy, floor(r - 12), 0, 360, P.dynamic_color("fx"), 20)
    end
  else
    P.restore("fx")
  end
end

function transitions.truth_ripple(t, ox, oy)
  ripple(t, ox, oy, 0, A.SIG_RIPPLE_CR)
end

function transitions.truth_ripple_cold(t, ox, oy)
  ripple(t, ox, oy, A.SIG_RIPPLE_CB, 0)
end

-- ---------------------------------------------------------------------------
-- HUD acoustics analogs (docs/HALO_CINEMA_V1.md §1.3)
-- ---------------------------------------------------------------------------

--- Chime: memory saved. Single ring, r 8→28, out_expo.
function transitions.chime(t, cx, cy)
  if _reduce_motion then
    arc(cx or CX, cy or CY, A.SIG_CHIME_R_TO, 0, 360, P.accent_success, 24)
    return
  end
  t = clamp(t, 0, 1)
  if t >= 1 then return end
  local r = lerp(A.SIG_CHIME_R_FROM, A.SIG_CHIME_R_TO, E.out_expo(t))
  arc(cx or CX, cy or CY, floor(r), 0, 360, P.accent_success, 24)
end

--- Chord: person recognized. 3-arc arpeggio (r 32/40/48) around an avatar.
function transitions.chord(t, cx, cy, confidence)
  cx, cy = cx or CX, cy or CY
  local total = A.SIG_CHORD_STEP_MS * 3
  local radii = { 32, 40, 48 }
  for i, r in ipairs(radii) do
    local visible = _reduce_motion or (t * total >= A.SIG_CHORD_STEP_MS * (i - 1))
    if visible then
      local sweep = (confidence or 1) * 360
      arc(cx, cy, r, -90, -90 + sweep, P.accent_memory, 24)
    end
  end
end

--- Rumble: privacy veil pre-slam. Full-field dim of every dynamic slot.
function transitions.rumble(t)
  MAT.init()
  if _reduce_motion then return end
  t = clamp(t, 0, 1)
  local drop = A.SIG_RUMBLE_Y_DROP * (1 - t)
  for _, name in ipairs(P.reserved_names()) do
    P.shift_dynamic(name, -drop, 0, 0)
  end
  if t >= 1 then P.restore_all() end
end

-- ---------------------------------------------------------------------------
-- Shared EXIT: geometry contracts, text cuts at t=0.4 (kill list #2 — no
-- more glyphs shrinking through floor()).
-- ---------------------------------------------------------------------------
function transitions.exit_contract(t)
  if _reduce_motion then
    return (t >= 1) and 0 or 1, t < 1
  end
  t = clamp(t, 0, 1)
  return 1 - t, t < 0.4
end

return transitions
