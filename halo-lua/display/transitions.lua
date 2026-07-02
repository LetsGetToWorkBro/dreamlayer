--- display/transitions.lua
--- Halo Cinema v1 motion signatures (docs/HALO_CINEMA_V1.md §1.1).
---
--- Six named signatures, extracted from renderer.lua for reuse:
---   S1 iris_bloom       card ENTER — radial mask reveal
---   S2 ghost_wake_text  WorldAnchorCard ENTER — Perlin condensation
---   S3 prism_slide      card→card crossfade — chromatic split fringes
---   S4 confidence_halo  HOLD idle — orbital confidence arc
---   S5 truth_ripple     Truth Lens verdict ENTER — ripple from eye landmark
---   S6 memory_comet     ProactiveMemoryCard ENTER — recency-angle comet
--- plus the HUD acoustics analogs (chime / chord / rumble) and the shared
--- exit_contract.
---
--- renderer.lua composes these; dream_renderer.lua calls ghost_wake_text and
--- iris_bloom for WorldAnchor / Synesthesia cards.
---
--- Every timing constant comes from display/animations.lua. Every color is a
--- palette token. Every signature honors reduce_motion: callers set it once
--- per card ENTER via transitions.set_reduce_motion(); each function then
--- renders its static, information-preserving variant.
---
--- Public API:
---   transitions.set_reduce_motion(flag) / transitions.reduce_motion()
---   transitions.enter_duration(sig_name)  -> ms
---   transitions.iris_bloom(t, accent)     -> gate radius (draws ring)
---   transitions.ghost_wake_text(x, y, text, size, t, seed_ms)
---   transitions.prism_slide(t)
---   transitions.confidence_halo(idle_ms, confidence, color)
---   transitions.truth_ripple(t, ox, oy)
---   transitions.truth_ripple_cold(t, ox, oy)
---   transitions.memory_comet(t, weeks_old, tx, ty, color)
---   transitions.comet_entry_angle(weeks_old) -> degrees
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
  iris       = A.SIG_IRIS_MS + A.SIG_IRIS_TRAIL_MS,
  ghost_wake = A.SIG_GHOSTWAKE_MS,
  ripple     = A.SIG_RIPPLE_MS,
  comet      = A.SIG_COMET_MS + A.SIG_IRIS_MS,
}

function transitions.enter_duration(sig)
  if _reduce_motion then return 0 end
  return ENTER_MS[sig] or A.ENTER_DURATION_MS
end

-- ---------------------------------------------------------------------------
-- S1 Iris Bloom
-- Collapsing accent ring from safe edge to content core; returns the current
-- gate radius — the caller reveals only elements inside that radius.
-- Trailing 60ms ramps the ghost_text slot luma for the "fade up" edge.
-- ---------------------------------------------------------------------------
function transitions.iris_bloom(t, accent)
  MAT.init()
  if _reduce_motion or t >= 1 then
    P.restore("ghost_text")
    return 0   -- gate open: everything visible
  end
  local ring_t  = clamp(t * (ENTER_MS.iris / A.SIG_IRIS_MS), 0, 1)
  local trail_t = clamp((t * ENTER_MS.iris - (ENTER_MS.iris - A.SIG_IRIS_TRAIL_MS))
                        / A.SIG_IRIS_TRAIL_MS, 0, 1)
  local r = lerp(A.SIG_IRIS_R_FROM, A.SIG_IRIS_R_TO, E.out_expo(ring_t))
  if ring_t < 1 then
    arc(CX, CY, floor(r), 0, 360, accent or P.accent_memory, 40)
  end
  -- Trailing edge: ghost tier fades up as the ring lands
  P.set_dynamic_y("ghost_text", lerp(160, 400, trail_t))
  return r
end

-- ---------------------------------------------------------------------------
-- S2 Ghost Wake
-- Per-character Perlin jitter converging over 320ms while the ghost slot
-- luma ramps 0 -> ghost. Character x-advance approximates typography "sm".
-- ---------------------------------------------------------------------------
local GHOSTWAKE_CHAR_W = 10   -- matches typography AVG_W.sm

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
  local amp   = A.SIG_GHOSTWAKE_JITTER_PX * (1 - E.in_out_cubic(t))
  local seed  = (seed_ms or 0) * 0.004
  local color = P.dynamic_color("ghost_text")
  local n     = #text
  local x0    = x - floor(n * GHOSTWAKE_CHAR_W / 2)
  for i = 1, n do
    local ch = text:sub(i, i)
    if ch ~= " " then
      local jx = E.perlin1d(seed + i * 7.13)  * amp
      local jy = E.perlin1d(seed + i * 13.7 + 51) * amp
      frame.display.text(ch, floor(x0 + (i - 1) * GHOSTWAKE_CHAR_W + jx),
                         floor(y + jy), color)
    end
  end
end

-- ---------------------------------------------------------------------------
-- S3 Prism Slide
-- Chromatic split fringes for the outgoing card: two accent rings drawn at
-- ±SPLIT_PX in the reserved prism_cool / prism_warm slots, whose chroma the
-- signature pushes apart (Cb+ / Cr−) and whose luma dies with t.
-- The outgoing card's geometry contract is handled by exit_contract; this
-- draws the refraction on top.
-- ---------------------------------------------------------------------------
function transitions.prism_slide(t)
  MAT.init()
  if _reduce_motion then return end
  t = clamp(t, 0, 1)
  local fade = 1 - t
  P.shift_dynamic("prism_cool", -fade * 0,  A.SIG_PRISM_CB * fade, 0)
  P.shift_dynamic("prism_warm", -fade * 0,  0, -A.SIG_PRISM_CR * fade)
  P.set_dynamic_y("prism_cool", 500 * fade)
  P.set_dynamic_y("prism_warm", 500 * fade)
  local off = floor(A.SIG_PRISM_SPLIT_PX * fade)
  if off >= 1 then
    local r = floor(lerp(56, 40, t))
    arc(CX + off, CY, r, 0, 360, P.dynamic_color("prism_cool"), 24)
    arc(CX - off, CY, r, 0, 360, P.dynamic_color("prism_warm"), 24)
  end
  if t >= 1 then
    P.restore("prism_cool")
    P.restore("prism_warm")
  end
end

-- ---------------------------------------------------------------------------
-- S4 Confidence Halo
-- Orbital arc: radius and sweep both encode confidence. One orbit per
-- SIG_HALO_PERIOD_MS. reduce_motion: same arc, static at 12 o'clock.
-- ---------------------------------------------------------------------------
function transitions.confidence_halo(idle_ms, confidence, color)
  confidence = clamp(confidence or 0.5, 0, 1)
  local r     = floor(A.SIG_HALO_R_BASE + confidence * A.SIG_HALO_R_CONF)
  local sweep = confidence * 360
  local a0    = -90
  if not _reduce_motion then
    a0 = a0 + ((idle_ms or 0) % A.SIG_HALO_PERIOD_MS) / A.SIG_HALO_PERIOD_MS * 360
  end
  arc(CX, CY, r, a0, a0 + sweep, color or P.accent_memory, 24)
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
-- S6 Memory Comet
-- Entry angle encodes recall recency: 12 o'clock = today, +30°/week
-- clockwise. Bezier from display edge to the card's text anchor with a
-- 3-sample fading tail; final 80ms widens the tail 1px (arrival shimmer).
-- reduce_motion: an 8px tick mark at the encoded angle on the card rim.
-- ---------------------------------------------------------------------------
function transitions.comet_entry_angle(weeks_old)
  local sweep = clamp((weeks_old or 0) * A.SIG_COMET_DEG_PER_WEEK,
                      0, A.SIG_COMET_MAX_DEG)
  return -90 + sweep   -- -90° = 12 o'clock, clockwise as memories age
end

local function comet_point(t, ang_rad, tx, ty)
  local ex = CX + 126 * math.cos(ang_rad)
  local ey = CY + 126 * math.sin(ang_rad)
  local mx, my = (ex + tx) / 2, (ey + ty) / 2
  -- control point pushed perpendicular for a swept-in path
  local px, py = -(ty - ey), (tx - ex)
  local plen = math.sqrt(px * px + py * py) + 0.001
  local cx = mx + px / plen * 40
  local cy = my + py / plen * 40
  local u = E.in_out_cubic(clamp(t, 0, 1))
  local mt = 1 - u
  return mt * mt * ex + 2 * mt * u * cx + u * u * tx,
         mt * mt * ey + 2 * mt * u * cy + u * u * ty
end

function transitions.memory_comet(t, weeks_old, tx, ty, color)
  color = color or P.memory_trace
  local ang = math.rad(transitions.comet_entry_angle(weeks_old))
  tx, ty = tx or CX, ty or CY
  if _reduce_motion then
    -- static recency tick on the rim
    if HAS_FRAME then
      local x1 = CX + 104 * math.cos(ang)
      local y1 = CY + 104 * math.sin(ang)
      local x2 = CX + 112 * math.cos(ang)
      local y2 = CY + 112 * math.sin(ang)
      frame.display.line(floor(x1), floor(y1), floor(x2), floor(y2), color)
    end
    return
  end
  if not HAS_FRAME or t >= 1 then return end
  t = clamp(t, 0, 1)
  local hx, hy = comet_point(t, ang, tx, ty)
  -- head
  local shimmer = (t * A.SIG_COMET_MS > A.SIG_COMET_MS - 80) and 1 or 0
  frame.display.circle(floor(hx), floor(hy), 2 + shimmer, color, true)
  -- tail: previous SIG_COMET_TAIL samples in fading shades
  local shades = { P.text_ghost, P.accent_memory_dim, P.accent_memory }
  for i = 1, A.SIG_COMET_TAIL do
    local tt = t - i * 0.06
    if tt > 0 then
      local x, y = comet_point(tt, ang, tx, ty)
      frame.display.circle(floor(x), floor(y), 1 + shimmer,
                           shades[((i - 1) % #shades) + 1], true)
    end
  end
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
