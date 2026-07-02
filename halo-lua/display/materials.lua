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
  -- Prism fringes alias the dream drift slots (3/4): dream mode and card
  -- crossfades are mutually exclusive, so the slots never fight.
  P.reserve_dynamic("prism_cool", P.accent_memory, 3)
  P.reserve_dynamic("prism_warm", P.accent_attention, 4)
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
  frame.display.text(tostring(text), math.floor(x), math.floor(y),
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
