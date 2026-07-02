--- display/prism.lua
--- Prism Lens: the world as a reactive psychedelic overlay.
---
--- A wonder mode, not a perception hack. It turns the HUD into a
--- kaleidoscope: a small set of radial arms, mirrored into `symmetry`
--- sectors, rotating slowly — drawn in the four dynamic sky slots whose
--- colours are *palette-cycled* through a rainbow ring
--- (display/palette_cycle.lua). So the colour flows through the arms with
--- almost no redraw cost, and the geometry only turns; the two motions
--- together read as breathing, trailing, impossibly-coloured light.
---
--- Safety by construction: this is aesthetic stylisation, NOT
--- neurostimulation. The palette cycle and rotation are slow and capped,
--- and reduce_motion freezes both to a still symmetric bloom — colour
--- without movement. It never flickers near photosensitivity thresholds.
---
--- Host contract: {t="prism", active=0|1, intensity=0..100,
---                 symmetry=n, hue_rate=n}. Intensity scales the arm count,
--- reach, and cycle speed; symmetry is the mirror count.
---
--- Public API:
---   prism.on_prism(msg)   BLE handler
---   prism.is_active()     render-precedence hook for main.lua
---   prism.draw(now_ms, opts)   one pass (caller owns clear/show)
---   prism.reset()         test hook

local PAL = require("display/palette")
local PaletteCycle = require("display/palette_cycle")

local HAS_FRAME = (type(_G.frame) == "table")

local M = {}
local CX, CY = 128, 128
local R_IN, R_OUT = 18, 118

-- a rainbow ring the four sky slots cycle through
local RAINBOW = { 0xE0435A, 0xE0A043, 0x43E06B, 0x439AE0, 0x7A6BE0, 0xE043C7 }
local SLOTS = { "sky", "energy", "drift_a", "drift_b" }

local _active     = false
local _intensity  = 0.6      -- 0..1
local _symmetry   = 6        -- mirror sectors
local _hue_rate   = 1.0      -- palette-cycle speed multiplier
local _cycle      = nil      -- built lazily (dream slots reserved by then)

local function fl(n) return math.floor(n + 0.5) end

local function cycle()
  if not _cycle then
    -- ~5s base period, sped up by intensity and hue_rate
    _cycle = PaletteCycle.new(SLOTS, RAINBOW,
      { period_ms = 5000, smooth = true })
  end
  return _cycle
end

--- {t="prism", active, intensity(0-100), symmetry, hue_rate}
function M.on_prism(msg)
  if msg.active ~= nil then _active = (tonumber(msg.active) or 0) ~= 0 end
  if msg.intensity ~= nil then
    _intensity = math.max(0, math.min(1, (tonumber(msg.intensity) or 60) / 100))
  end
  if msg.symmetry ~= nil then
    _symmetry = math.max(2, math.min(12, math.floor(tonumber(msg.symmetry) or 6)))
  end
  if msg.hue_rate ~= nil then
    _hue_rate = math.max(0.1, math.min(4, tonumber(msg.hue_rate) or 1))
  end
  if not _active then PAL.restore_all() end   -- release the sky slots
end

function M.is_active() return _active end

--- Draw one kaleidoscope pass. reduce_motion freezes rotation and holds
--- the palette at its base arrangement (a still symmetric bloom).
function M.draw(now_ms, opts)
  if not _active or not HAS_FRAME then return end
  opts = opts or {}
  now_ms = now_ms or 0
  local reduce = opts.reduce_motion

  -- palette cycling drives the colour; reduce_motion holds the base ring
  local cy = cycle()
  if reduce then
    cy:tick(0, { reduce_motion = true })
  else
    cy:tick(fl(now_ms * _hue_rate))
  end
  local slots = cy:slots()

  -- arm count and reach scale with intensity
  local arms = 3 + fl(_intensity * 5)          -- 3..8 arms per sector
  local reach = R_IN + (R_OUT - R_IN) * (0.5 + 0.5 * _intensity)
  local spin = reduce and 0 or (now_ms * 0.00004 * _hue_rate) % (2 * math.pi)
  local sector = (2 * math.pi) / _symmetry

  for s = 0, _symmetry - 1 do
    local base = s * sector + spin
    for a = 1, arms do
      -- each arm sits at a fixed offset in the sector, drawn in a cycling
      -- slot so its colour flows as the palette turns
      local frac = a / (arms + 1)
      local ang = base + frac * sector
      local col = slots[((a - 1) % #slots) + 1]
      local r0 = R_IN + frac * 6
      local r1 = R_IN + (reach - R_IN) * (0.4 + 0.6 * frac)
      local x0 = CX + r0 * math.cos(ang)
      local y0 = CY + r0 * math.sin(ang)
      local x1 = CX + r1 * math.cos(ang)
      local y1 = CY + r1 * math.sin(ang)
      frame.display.line(fl(x0), fl(y0), fl(x1), fl(y1), col)
      -- a bloom dot at the tip, brightest slot
      frame.display.circle(fl(x1), fl(y1), 2, slots[1], true)
    end
  end
end

function M.reset()
  _active, _intensity, _symmetry, _hue_rate = false, 0.6, 6, 1.0
  _cycle = nil
end

return M
