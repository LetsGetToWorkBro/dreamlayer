--- display/prism.lua
--- Prism Lens: the world as a reactive psychedelic overlay.
--- Lumen rebuild (docs/cinema_v2/lumen.md).
---
--- A wonder mode, not a perception hack. The HUD becomes a kaleidoscope:
--- radial arms mirrored into `symmetry` sectors, two thin halo rings
--- counter-rotating against them, everything drawn in the four dynamic
--- sky slots whose colours are *palette-cycled* through a rainbow ring
--- (display/palette_cycle.lua) — the colour flows through the standing
--- geometry at almost no redraw cost.
---
--- What Lumen changed (and one bug it fixed): v1 passed raw slot INDICES
--- (1..4) to the draw calls, which the 0xRRGGBB colour convention reads
--- as near-black — the kaleidoscope rendered invisibly. Arms now draw in
--- each slot's BASE HEX (PAL.dynamic_color), which the indexed panel and
--- the raster harness both resolve to the slot's live cycled colour.
--- New: the field blooms open on a snappy spring over PRISM_BLOOM_MS;
--- the rotation *breathes* (slow sinusoidal rate, never a fixed spin);
--- the halo rings counter-rotate; arm tips shimmer on per-arm Perlin
--- phases; and the whole field floats at AIR parallax depth.
---
--- Safety by construction: aesthetic stylisation, NOT neurostimulation.
--- Cycle and rotation rates are slow and capped; reduce_motion freezes
--- everything to a still symmetric bloom — colour without movement. It
--- never flickers near photosensitivity thresholds.
---
--- Host contract (unchanged): {t="prism", active=0|1, intensity=0..100,
---                 symmetry=n, hue_rate=n}. Intensity scales arm count,
--- reach, and cycle speed; symmetry is the mirror count.
---
--- Public API:
---   prism.on_prism(msg)        BLE handler
---   prism.is_active()          render-precedence hook for main.lua
---   prism.draw(now_ms, opts)   one pass (caller owns clear/show)
---   prism.reset()              test hook

local PAL = require("display/palette")
local PaletteCycle = require("display/palette_cycle")
local A  = require("display.animations")
local E  = require("lib.easing")
local PX = require("display.parallax")

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
local _bloom_t0   = nil      -- set by the first draw after activation
local _close_t0   = nil      -- set when the host turns the lens off:
                             -- the field folds back in before yielding

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
  if msg.active ~= nil then
    local was = _active
    _active = (tonumber(msg.active) or 0) ~= 0
    if _active and not was then
      _bloom_t0, _close_t0 = nil, nil            -- re-bloom on entry
    elseif was and not _active then
      if HAS_FRAME then
        _close_t0 = "pending"                    -- fold in, then yield
        _active = true                           -- own the display while closing
      else
        PAL.restore_all()                        -- headless: yield instantly
      end
    end
  end
  if msg.intensity ~= nil then
    _intensity = math.max(0, math.min(1, (tonumber(msg.intensity) or 60) / 100))
  end
  if msg.symmetry ~= nil then
    _symmetry = math.max(2, math.min(12, math.floor(tonumber(msg.symmetry) or 6)))
  end
  if msg.hue_rate ~= nil then
    _hue_rate = math.max(0.1, math.min(4, tonumber(msg.hue_rate) or 1))
  end
end

function M.is_active() return _active end

--- One thin halo ring: 8 arc segments with gaps, rotated by `phase`.
local function halo_ring(r, phase, color, ox, oy)
  local segs = 8
  local span = (2 * math.pi) / segs
  local gap = span * 0.35
  for s = 0, segs - 1 do
    local a0 = phase + s * span
    local a1 = a0 + span - gap
    local steps = 3
    local px = CX + ox + r * math.cos(a0)
    local py = CY + oy + r * math.sin(a0)
    for i = 1, steps do
      local a = a0 + (a1 - a0) * i / steps
      local x = CX + ox + r * math.cos(a)
      local y = CY + oy + r * math.sin(a)
      frame.display.line(fl(px), fl(py), fl(x), fl(y), color)
      px, py = x, y
    end
  end
end

--- Draw one kaleidoscope pass. reduce_motion freezes rotation, bloom,
--- and shimmer, and holds the palette at its base arrangement — a still
--- symmetric bloom, fully drawn.
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
  -- draw in the slots' BASE hexes: the panel resolves them to the live
  -- cycled colours (the v1 slot-index bug drew this field in near-black)
  local colors = {}
  for i, name in ipairs(SLOTS) do colors[i] = PAL.dynamic_color(name) end

  -- bloom-in: the field unfolds on a snappy spring after activation;
  -- on deactivation it folds back in over the same window, then yields
  -- the display (reduce_motion: closing is an immediate hand-off)
  local bloom = 1
  if _close_t0 then
    if reduce then
      _active, _close_t0 = false, nil
      PAL.restore_all()
      return
    end
    if _close_t0 == "pending" then _close_t0 = now_ms end
    local ct = (now_ms - _close_t0) / A.PRISM_BLOOM_MS
    if ct >= 1 then
      _active, _close_t0 = false, nil
      PAL.restore_all()
      return
    end
    bloom = 1 - E.in_out_cubic(math.max(0, ct))
  elseif not reduce then
    if not _bloom_t0 then _bloom_t0 = now_ms end
    bloom = E.spring(math.min(1, (now_ms - _bloom_t0) / A.PRISM_BLOOM_MS),
                     A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA)
  end

  -- the whole field floats at AIR parallax depth
  local ox, oy = PX.offset("air")

  -- ---- the Lumen-2 mandala: a full geometric kaleidoscope. Four layers
  -- over the standing palette cycle — fronds, a nested polygon lattice,
  -- orbiting petals, and a breathing central eye. Deliberately lavish (a
  -- hidden wonder mode, not a battery-budget citizen), but still SAFE by
  -- construction: every motion is a slow sinusoid or the capped spin —
  -- nothing steps, nothing strobes, nothing approaches photosensitivity
  -- thresholds. reduce_motion freezes all phase terms into one still,
  -- fully-drawn mandala.
  -- fronds per sector scale with intensity, then yield to the frame
  -- budget as symmetry climbs: sectors × arms stays ≤ 24, and the chevron
  -- branches only draw at ≤8 sectors — lavish at the discovery's default
  -- (symmetry 6), lean at the geometric extremes, never over DRAW_CALLS_MAX
  local arms = 3 + fl(_intensity * 3)          -- 3..6 fronds per sector
  arms = math.max(2, math.min(arms, fl(24 / _symmetry)))
  local branches = _symmetry <= 8
  local reach = R_IN + (R_OUT - R_IN) * (0.5 + 0.5 * _intensity) * bloom
  local spin, breath, tsec = 0, 1, 0
  if not reduce then
    breath = 1 + 0.5 * math.sin(2 * math.pi * now_ms / A.PRISM_BREATH_MS)
    spin = (now_ms * A.PRISM_SPIN_RATE * _hue_rate * breath) % (2 * math.pi)
    tsec = now_ms * 0.001
  end
  local sector = (2 * math.pi) / _symmetry
  local function pt(r, ang)
    return fl(CX + ox + r * math.cos(ang)), fl(CY + oy + r * math.sin(ang))
  end

  -- L1 · fronds: each arm is a stem with two chevron branches — mirrored
  -- across every sector, the classic kaleidoscope fern
  for s2 = 0, _symmetry - 1 do
    local base = s2 * sector + spin
    for a = 1, arms do
      local frac = a / (arms + 1)
      local ang = base + frac * sector
      local col = colors[((a - 1) % #colors) + 1]
      local r1 = R_IN + (reach - R_IN) * (0.4 + 0.6 * frac)
      local x0, y0 = pt(R_IN + frac * 6, ang)
      local x1, y1 = pt(r1, ang)
      frame.display.line(x0, y0, x1, y1, col)
      for _, bp in ipairs(branches and { 0.55, 0.8 } or {}) do
        local br = R_IN + (r1 - R_IN) * bp
        local bx, by = pt(br, ang)
        local blen = (r1 - R_IN) * 0.22 * breath
        for _, sgn in ipairs({ -1, 1 }) do
          local ex, ey = pt(br + blen, ang + sgn * 0.38)
          frame.display.line(bx, by, ex, ey, colors[((a) % #colors) + 1])
        end
      end
      local tip = 2
      if not reduce then
        tip = 1 + fl(math.abs(E.perlin1d(tsec + s2 * 7.13 + a * 13.7)) + 0.5)
      end
      frame.display.circle(fl(x1), fl(y1), tip, colors[1], true)
    end
  end

  -- L2 · nested polygon lattice: three counter-rotating symmetry-gons,
  -- their vertices webbed — the interference between the three spins is
  -- the trip
  local ring_r = { reach * 0.38, reach * 0.62, reach * 0.86 }
  local ring_spin = { spin * 0.7, -spin * 0.9, spin * 0.5 + 0.4 }
  local verts = {}
  for k = 1, 3 do
    verts[k] = {}
    for v = 0, _symmetry - 1 do
      local ang = ring_spin[k] + v * sector + (k - 1) * sector * 0.5
      local x, y = pt(ring_r[k], ang)
      verts[k][v + 1] = { x, y }
    end
  end
  for k = 1, 3 do
    local col = colors[((k + 1) % #colors) + 1]
    for v = 1, _symmetry do
      local a2 = verts[k][v]
      local b2 = verts[k][(v % _symmetry) + 1]
      frame.display.line(a2[1], a2[2], b2[1], b2[2], col)
    end
  end
  for v = 1, _symmetry do                       -- spokes: mid ring → outer ring
    local a2, b2 = verts[2][v], verts[3][v]
    frame.display.line(a2[1], a2[2], b2[1], b2[2], colors[2])
  end

  -- L3 · orbiting petals: paired dots riding between the lattice rings,
  -- each on its own slow phase, pulsing size with the breath
  for v = 0, math.min(_symmetry * 2, 16) - 1 do
    local ph = reduce and 0 or (tsec * 0.6 + v * 1.7)
    local orb = reach * (0.5 + 0.24 * math.sin(ph))
    local ang = -spin * 1.2 + v * (math.pi / _symmetry)
    local x, y = pt(orb, ang)
    local pr = fl(1.5 + 1.5 * (0.5 + 0.5 * math.sin(ph * 1.3)) * breath)
    frame.display.circle(x, y, pr, colors[(v % #colors) + 1], true)
  end

  -- L4 · the eye: concentric pulse at the core, and a slow inner triangle
  for i = 0, 2 do
    local er = fl((R_IN - 2) * bloom * (0.4 + 0.3 * i)
                  * (1 + (reduce and 0 or 0.12 * math.sin(tsec * 1.1 + i))))
    if er > 1 then
      frame.display.circle(fl(CX + ox), fl(CY + oy), er,
                           colors[(i % #colors) + 1], false)
    end
  end
  local tri = {}
  for v = 0, 2 do
    local ang = -spin * 0.6 + v * (2 * math.pi / 3)
    local x, y = pt(R_IN * 0.9 * bloom, ang)
    tri[v + 1] = { x, y }
  end
  for v = 1, 3 do
    local a2, b2 = tri[v], tri[(v % 3) + 1]
    frame.display.line(a2[1], a2[2], b2[1], b2[2], colors[4])
  end

  -- the counter-rotating halo rings hold the outer edge
  if bloom > 0.5 then
    halo_ring(A.PRISM_RING_R_A * bloom, -spin * 1.4, colors[2], ox, oy)
    halo_ring(A.PRISM_RING_R_B * bloom, -spin * 0.8 + 0.3, colors[4], ox, oy)
  end
end

function M.reset()
  _active, _intensity, _symmetry, _hue_rate = false, 0.6, 6, 1.0
  _cycle, _bloom_t0, _close_t0 = nil, nil, nil
end

return M
