--- display/materials.lua
--- Halo Cinema v1 material tiers: Air / Ghost / Solid.
---
--- Every drawn element belongs to exactly one tier
--- (docs/HALO_CINEMA_V1.md §1.2):
---   AIR    ambient field, never information-bearing  (dream particles, rings)
---   GHOST  present-but-not-primary information        (echoes, footers)
---   SOLID  the one thing that matters                 (primary line, verdict)
---
--- Since the display is 4bpp indexed with no alpha channel, "opacity" is
--- faked two ways:
---   a) ghost-tier text draws in the dynamic `ghost_text` palette slot whose
---      luma the renderer animates via palette.set_dynamic_y()
---   b) area fills use compile-time ordered-dither skip patterns
--- Text is never dithered (glyphs garble at 10-13px sizes).
---
--- Public API:
---   materials.AIR / materials.GHOST / materials.SOLID   tier ids
---   materials.init()                                    reserve slots (idempotent)
---   materials.draw_ghost_text(x, y, text, size, intensity)
---   materials.dither_fill(x, y, w, h, color, pattern)
---   materials.DITHER_25 / materials.DITHER_50           pattern tables

local P   = require("display.palette")

local HAS_FRAME = (type(_G.frame) == "table")

local M = {}

M.AIR   = "air"
M.GHOST = "ghost"
M.SOLID = "solid"

-- ---------------------------------------------------------------------------
-- Dither patterns: {dx, dy} offsets *kept* inside each 2x2 cell.
-- DITHER_50 keeps 2 of 4 pixels (checker), DITHER_25 keeps 1 of 4.
-- Compile-time constants — never built per frame.
-- ---------------------------------------------------------------------------
M.DITHER_50 = { {0, 0}, {1, 1} }
M.DITHER_25 = { {0, 0} }
M.DITHER_CELL = 2

-- ---------------------------------------------------------------------------
-- Dynamic slot reservations (idempotent; shared map with the host — see
-- hud/themes.py DYNAMIC_SLOTS). Dream ambient slots 1-4 are reserved by
-- dream_renderer; materials owns the ghost/fx slots.
-- ---------------------------------------------------------------------------
local _initialized = false

function M.init()
  if _initialized then return end
  _initialized = true
  P.reserve_dynamic("ghost_text", P.text_ghost, 5)
  P.reserve_dynamic("fx",         P.accent_memory, 6)
  -- Meridian: the v1 prism fringes are gone (docs/CINEMA_V2_DELTAS.md §2),
  -- so drift slots 3/4 have exactly one owner — the dream weather. The
  -- mode-transition slot-contention hole in the v1 risk register is closed
  -- structurally, not patched.
end

--- Draw ghost-tier text. `intensity` in [0,1] maps to the ghost slot's luma
--- (0 -> invisible, 1 -> full text_ghost luma x ~1.4 for legibility ceiling).
--- The luma ramp is a palette operation, so every ghost glyph on screen
--- shares the same intensity — by design: ghosts are one ambient layer.
function M.draw_ghost_text(x, y, text, size, intensity)
  M.init()
  intensity = math.max(0, math.min(1, intensity or 1))
  P.set_dynamic_y("ghost_text", intensity * 560)
  if not HAS_FRAME then return end
  -- Solid: the long-ignored size arg is live (primitives set_font seam)
  local PR = require("display.primitives")
  PR.text_center(x, y, tostring(text), size or "sm",
                 P.dynamic_color("ghost_text"))
end

--- Ordered-dither area fill for Air/Ghost tier fills.
--- pattern: M.DITHER_25 (air) or M.DITHER_50 (ghost).
function M.dither_fill(x, y, w, h, color, pattern)
  if not HAS_FRAME then return end
  pattern = pattern or M.DITHER_50
  local cell = M.DITHER_CELL
  local kept = {}
  for _, off in ipairs(pattern) do kept[off[2] * cell + off[1]] = true end
  for py = 0, h - 1 do
    local run_x = nil
    for px = 0, w - 1 do
      local key = ((y + py) % cell) * cell + ((x + px) % cell)
      if kept[key] then
        if not run_x then run_x = x + px end
      elseif run_x then
        frame.display.line(run_x, y + py, x + px - 1, y + py, color)
        run_x = nil
      end
    end
    if run_x then
      frame.display.line(run_x, y + py, x + w - 1, y + py, color)
    end
  end
end

-- ---------------------------------------------------------------------------
-- Meridian Solid material system (docs/cinema_v2/solid.md).
-- Translucency on a renderer with no alpha and a per-frame call budget:
-- row-gap scanline fills — ONE line call per row (per-pixel dithering
-- costs one call per pixel and is banned for areas). Gradients: strokes
-- whose segment color walks a token ramp — same call count as a plain
-- stroke. Bloom: two dim outline circles. Every function returns its
-- draw-call count so the budget tests can pin the cost table.
--
-- Rules: panes only in surface-luma colors (additive display — richer,
-- not brighter); callers gate panes/fills on exit_t == 0; text is never
-- drawn in pane color; privacy-class cards get no pane.
-- ---------------------------------------------------------------------------

M.PANE = P.surface

-- Static gradient ramps (bright -> dim). RAMP_MEMORY_LIVE leads with the
-- card band bases so Lumen's conduct wave still flows on the bright half.
local A_OK, A = pcall(require, "display.animations")
M.RAMP_MEMORY      = { P.memory_trace, P.accent_memory_static,
                       P.accent_memory_dim, P.border_subtle }
M.RAMP_MEMORY_LIVE = A_OK and { A.SPEC_BASE_A, A.SPEC_BASE_B,
                                P.accent_memory_dim, P.border_subtle }
                     or M.RAMP_MEMORY
M.RAMP_SUCCESS     = { P.accent_success, P.accent_success_dim,
                       P.border_subtle }

-- Bloom halo color pairs: bright element color -> its dim twin.
local BLOOM_DIM = {
  [P.memory_trace]         = P.accent_memory_dim,
  [P.accent_memory_static] = P.accent_memory_dim,
  [P.accent_memory]        = P.accent_memory_dim,
  [P.accent_success]       = P.accent_success_dim,
  [P.accent_attention]     = P.accent_attention_dim,
  [P.warning_amber]        = P.warning_amber_dim,
  [P.confidence_high]      = P.accent_memory_dim,
  [P.confidence_med]       = P.accent_memory_dim,
  [P.confidence_low]       = P.warning_amber_dim,
}

local function fl(n) return math.floor(n + 0.5) end

--- Translucent disc: horizontal chord lines every `row_gap` rows inside
--- a circle, 2px inset. Cost = floor(2r/row_gap) calls (r=62, gap=3: 41).
function M.glass_disc(cx, cy, r, color, row_gap)
  color = color or M.PANE
  row_gap = math.max(2, row_gap or 3)
  local calls = 0
  if not HAS_FRAME then return calls end
  for y = cy - r + row_gap, cy + r - 1, row_gap do
    local dy = y - cy
    local half = math.sqrt(math.max(0, r * r - dy * dy)) - 2
    if half >= 1 then
      frame.display.line(fl(cx - half), fl(y), fl(cx + half), fl(y), color)
      calls = calls + 1
    end
  end
  return calls
end

--- Translucent capsule (rounded-end horizontal box). Cost ≈ h/row_gap.
function M.glass_capsule(x, y, w, h, color, row_gap)
  color = color or M.PANE
  row_gap = math.max(2, row_gap or 3)
  local calls = 0
  if not HAS_FRAME then return calls end
  local hr = h / 2
  for ry = y + row_gap, y + h - 1, row_gap do
    local dy = ry - y
    local cap = math.min(dy, h - dy)
    local inset = 0
    if cap < hr then
      inset = hr - math.sqrt(math.max(0, hr * hr - (hr - cap) * (hr - cap)))
    end
    local x0, x1 = x + inset + 1, x + w - inset - 1
    if x1 > x0 then
      frame.display.line(fl(x0), fl(ry), fl(x1), fl(ry), color)
      calls = calls + 1
    end
  end
  return calls
end

--- Gradient line: split into #ramp equal segments, one call each.
function M.grad_line(x0, y0, x1, y1, ramp)
  ramp = ramp or M.RAMP_MEMORY
  if not HAS_FRAME then return 0 end
  local n = #ramp
  local px, py = x0, y0
  for i = 1, n do
    local t = i / n
    local nx, ny = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
    frame.display.line(fl(px), fl(py), fl(nx), fl(ny), ramp[i])
    px, py = nx, ny
  end
  return n
end

--- Gradient arc: identical cost to a plain arc; segment color walks the
--- ramp from a0 (ramp[1], bright) to a1 (ramp[#ramp], dim).
function M.grad_arc(cx, cy, r, a0, a1, ramp, steps)
  ramp = ramp or M.RAMP_MEMORY
  steps = steps or 32
  if not HAS_FRAME or r <= 0 then return 0 end
  local sweep = a1 - a0
  local function pt(deg)
    local rd = math.rad(deg)
    return cx + r * math.cos(rd), cy + r * math.sin(rd)
  end
  local x0, y0 = pt(a0)
  for i = 1, steps do
    local x1, y1 = pt(a0 + sweep * i / steps)
    local ci = math.min(#ramp, math.ceil(i / steps * #ramp))
    frame.display.line(fl(x0), fl(y0), fl(x1), fl(y1), ramp[ci])
    x0, y0 = x1, y1
  end
  return steps
end

--- Gradient quadratic bezier: CONTINUOUS (no 7/12 dash duty — the ramp
--- replaces that fake alpha). Color walks the ramp along the curve.
function M.grad_bezier(p0x, p0y, p1x, p1y, p2x, p2y, ramp, steps)
  ramp = ramp or M.RAMP_MEMORY
  steps = steps or 24
  if not HAS_FRAME then return 0 end
  local px, py = p0x, p0y
  for i = 1, steps do
    local t = i / steps
    local mt = 1 - t
    local x = mt * mt * p0x + 2 * mt * t * p1x + t * t * p2x
    local y = mt * mt * p0y + 2 * mt * t * p1y + t * t * p2y
    local ci = math.min(#ramp, math.ceil(i / steps * #ramp))
    frame.display.line(fl(px), fl(py), fl(x), fl(y), ramp[ci])
    px, py = x, y
  end
  return steps
end

--- Optical bloom: two dim halo circles just outside a bright element.
function M.bloom_ring(cx, cy, r, color)
  if not HAS_FRAME then return 0 end
  frame.display.circle(fl(cx), fl(cy), fl(r + 2),
                       BLOOM_DIM[color] or P.border_subtle, false)
  frame.display.circle(fl(cx), fl(cy), fl(r + 5), P.border_subtle, false)
  return 2
end

--- Tier of a color token: SOLID for static semantic colors, GHOST/AIR for
--- dynamic-slot colors. Used by debug asserts, not by the hot path.
function M.tier_of(name)
  if name == "ghost_text" then return M.GHOST end
  if name == "sky" or name == "energy" or name == "drift_a" or name == "drift_b" then
    return M.AIR
  end
  return M.SOLID
end

--- Test hook.
function M._reset_for_test()
  _initialized = false
end

return M
