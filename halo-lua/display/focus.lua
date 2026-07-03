--- display/focus.lua
--- The Focus law: condensation / recession (docs/cinema_v2/focus.md).
--- One motion law replaces four v1 signatures (Iris Bloom, Prism Slide,
--- Confidence Halo orbit, Memory Comet — docs/CINEMA_V2_DELTAS.md §1-§4):
--- content is drawn inward into focus FROM its horizon angle, holds with
--- a static ring whose sweep is its confidence, and goes home when
--- released. Nothing materializes; nothing dies.
---
--- Public API (renderer.lua composes these):
---   focus.enter_ms() / focus.recede_ms()
---   focus.travel(t, origin_deg, color)          -- head+tail, rim -> core
---   focus.landing_ring(t, accent)               -- r 56->36 collapse + ghost ramp
---   focus.hold_ring(confidence, color)          -- static arc, sweep = conf
---   focus.recede(t, origin_deg)                 -- reverse flight home
---   focus.origin_or_now(card) -> deg            -- card.origin_deg | -90

local A   = require("display.animations")
local P   = require("display.palette")
local E   = require("lib.easing")
local TR  = require("display.transitions")
local PX  = require("display.parallax")

local HAS_FRAME = (type(_G.frame) == "table")

local M = {}

local CX, CY = 128, 128

local function fl(n) return math.floor(n + 0.5) end
local function clamp(v, lo, hi) return math.max(lo, math.min(hi, v)) end
local function lerp(a, b, t) return a + (b - a) * t end

-- Focus geometry floats at RING parallax depth (one layer above the rim,
-- below nothing) — content and text stay at LOCK and never move.
local function polar(r, deg)
  local ox, oy = PX.offset("ring")
  local rad = math.rad(deg)
  return CX + ox + r * math.cos(rad), CY + oy + r * math.sin(rad)
end

local function arc(r, a0, a1, color, steps)
  if not HAS_FRAME or r <= 0 then return end
  steps = steps or 40
  local sweep = a1 - a0
  local x0, y0 = polar(r, a0)
  for i = 1, steps do
    local x1, y1 = polar(r, a0 + sweep * i / steps)
    frame.display.line(fl(x0), fl(y0), fl(x1), fl(y1), color)
    x0, y0 = x1, y1
  end
end

function M.enter_ms()
  if TR.reduce_motion() then return 0 end
  return A.SIG_FOCUS_TRAVEL_MS + A.SIG_FOCUS_LAND_MS
end

function M.recede_ms()
  if TR.reduce_motion() then return 0 end
  return A.SIG_RECEDE_MS
end

--- Cards without a temporal origin condense from "now" (12 o'clock).
function M.origin_or_now(card)
  local deg = card and tonumber(card.origin_deg)
  return deg or A.MER_NOW_DEG
end

-- ---------------------------------------------------------------------------
-- Travel (Lumen): anticipation dip, squash-stretch head, and a 5-sample
-- phosphor tail along a perpendicular-offset bezier from
-- (MER_RIM_R, origin_deg) to the content core. The bezier takes an
-- ALREADY-EASED parameter u — callers choose the physics (anticipate on
-- condensation, soft spring on recession).
-- ---------------------------------------------------------------------------
local function bezier_point(u, x0, y0, x1, y1)
  local mx, my = (x0 + x1) / 2, (y0 + y1) / 2
  local px, py = -(y1 - y0), (x1 - x0)
  local plen = math.sqrt(px * px + py * py) + 0.001
  local cx = mx + px / plen * 24
  local cy = my + py / plen * 24
  local mt = 1 - u
  return mt * mt * x0 + 2 * mt * u * cx + u * u * x1,
         mt * mt * y0 + 2 * mt * u * cy + u * u * y1
end

--- Head + tail at eased parameter u; raw t drives the squash envelope
--- (peaks mid-flight, zero at both ends — geometry only, never text).
local function head_and_tail(u, t, x0, y0, x1, y1, head_color)
  if not HAS_FRAME then return end
  local hx, hy = bezier_point(u, x0, y0, x1, y1)
  frame.display.circle(fl(hx), fl(hy), 3, head_color, true)
  -- squash-stretch: a trailing 2px lobe elongates the head along its
  -- velocity at mid-flight
  local e = A.SQUASH_MAX * math.sin(math.pi * clamp(t, 0, 1))
  if e > 0.02 and u > 0.05 then
    local sx, sy = bezier_point(math.max(0, u - e * 0.2), x0, y0, x1, y1)
    frame.display.circle(fl(sx), fl(sy), 2, head_color, true)
  end
  -- phosphor tail: two solid embers, then ghost-slot samples whose shared
  -- luma the flight decays — the streak cools behind the head
  local shades = { P.accent_memory, P.accent_memory_dim }
  for i = 1, A.TRAIL_SAMPLES do
    local uu = u - i * A.TRAIL_STEP_T
    if uu > 0 then
      local x, y = bezier_point(uu, x0, y0, x1, y1)
      local color = shades[i] or P.dynamic_color("ghost_text")
      frame.display.circle(fl(x), fl(y), i == 1 and 2 or 1, color, true)
    end
  end
end

--- Condensation travel phase. t in [0,1]: an anticipation pull-back
--- toward the rim, then the flight (easing.anticipate composes both).
function M.travel(t, origin_deg, color)
  if TR.reduce_motion() then return end
  t = clamp(t, 0, 1)
  local ox, oy = polar(A.MER_RIM_R, origin_deg or A.MER_NOW_DEG)
  local p = E.anticipate(t, A.ANTICIPATE_FRAC, 1.0)
  if p < 0 then
    -- the head sinks ANTICIPATE_PX outward past the rim before it flies
    local rad = math.rad(origin_deg or A.MER_NOW_DEG)
    local r = A.MER_RIM_R - p * A.ANTICIPATE_PX   -- p negative: outward
    if HAS_FRAME then
      frame.display.circle(fl(CX + r * math.cos(rad)),
                           fl(CY + r * math.sin(rad)), 3,
                           color or P.accent_memory, true)
    end
    return
  end
  -- the tail's ghost samples share the ghost slot: hot at launch, cooling
  -- as the head lands (the landing ramp then takes the slot upward)
  P.set_dynamic_y("ghost_text", 160 + 240 * (1 - t))
  head_and_tail(p, t, ox, oy, CX, CY, color or P.accent_memory)
end

--- Landing phase: ring collapses r 56->36 on a snappy spring — the
--- rebound is the "click" of focus landing (Lumen; was out_expo) —
--- while content draws inside; the ghost slot Y-ramps over the trailing
--- SIG_FOCUS_TRAIL_MS. t in [0,1] of SIG_FOCUS_LAND_MS.
function M.landing_ring(t, accent)
  local MAT = require("display.materials")
  MAT.init()
  if TR.reduce_motion() or t >= 1 then
    P.restore("ghost_text")
    return
  end
  t = clamp(t, 0, 1)
  local r = lerp(A.SIG_FOCUS_LAND_R_FROM, A.SIG_FOCUS_LAND_R_TO,
                 E.spring(t, A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA))
  arc(fl(r), 0, 360, accent or P.accent_memory, 40)
  local trail_frac = A.SIG_FOCUS_TRAIL_MS / A.SIG_FOCUS_LAND_MS
  local trail_t = clamp((t - (1 - trail_frac)) / trail_frac, 0, 1)
  P.set_dynamic_y("ghost_text", lerp(160, 400, trail_t))
end

--- The landed focus ring: static, sweep = confidence. This is the card's
--- certainty gauge during HOLD; reduce_motion variant is identical (the
--- first signature whose reduce path is a no-op — the v2 standard).
--- Lumen: for the first SPEC_SWEEP_MS of HOLD a bright glint runs once
--- along the swept arc — light catching the ring as it settles. The
--- glint is an overdraw in the confidence family's brightest member;
--- the ring itself (color = confidence) never changes, and after the
--- sweep the hold frame is exactly the pre-Lumen static ring.
function M.hold_ring(confidence, color, hold_ms)
  local conf = clamp(confidence or 0.5, 0, 1)
  local sweep = conf * 360
  if sweep < 4 then return end
  -- segment count follows the sweep: a sliver costs a sliver's draw calls
  local steps = math.max(6, fl(sweep / 7.5))
  arc(A.SIG_FOCUS_RING_R, -90, -90 + sweep, color or P.accent_memory, steps)
  if hold_ms and hold_ms < A.SPEC_SWEEP_MS and not TR.reduce_motion() then
    local st = hold_ms / A.SPEC_SWEEP_MS
    local glint_w = math.min(14, sweep * 0.15)
    local g0 = -90 + (sweep - glint_w) * E.in_out_sine(st)
    arc(A.SIG_FOCUS_RING_R, g0, g0 + glint_w, P.confidence_high, 3)
  end
end

--- Recession flight home. t in [0,1] of SIG_RECEDE_MS. The caller
--- (renderer) handles content contraction + text cut via exit_contract
--- and fires horizon.pulse_mark on completion. Lumen: the flight eases
--- on the soft spring — it decelerates INTO the rim and settles, rather
--- than escaping at speed (CINEMA_V2_RISKS.md §3 anticipated this).
function M.recede(t, origin_deg)
  if TR.reduce_motion() then return end
  t = clamp(t, 0, 1)
  local ox, oy = polar(A.MER_RIM_R, origin_deg or A.MER_NOW_DEG)
  P.set_dynamic_y("ghost_text", 160 + 240 * (1 - t))
  head_and_tail(E.spring(t, A.SPRING_ZETA_SOFT, A.SPRING_OMEGA), t,
                CX, CY, ox, oy, P.accent_memory_dim)
  local ring_r = fl(A.SIG_FOCUS_LAND_R_TO * (1 - t))
  if ring_r > 2 and t < 0.5 then
    arc(ring_r, 0, 360, P.accent_memory_dim, 24)
  end
end

--- reduce_motion condensation: an 8px static tick at the origin angle
--- carries the temporal-origin reading (the comet's reduce variant,
--- generalized). Drawn once during HOLD alongside the full-sweep ring.
function M.origin_tick(origin_deg, color)
  if not HAS_FRAME then return end
  local rad = math.rad(origin_deg or A.MER_NOW_DEG)
  local x1 = CX + 100 * math.cos(rad)
  local y1 = CY + 100 * math.sin(rad)
  local x2 = CX + 108 * math.cos(rad)
  local y2 = CY + 108 * math.sin(rad)
  frame.display.line(fl(x1), fl(y1), fl(x2), fl(y2), color or P.accent_memory)
end

return M
