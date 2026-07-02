--- display/dream_renderer.lua
--- Dream Mode renderer: palette weather + particle system + ghost overlay.
---
--- Called by host_comm_dream.lua when t="palette", t="geometry" or
--- t="line_field" frames arrive. Also exports render_world_anchor(),
--- render_synesthesia() and draw_synesthesia_v2() for card types.
---
--- Architecture (Halo Cinema v1)
--- -----------------------------
--- DreamRenderer maintains:
---   _particles[]     -- 24 particle positions driven by mic energy
---   _line_field_v2[] -- 12 curl-noise vectors streamed from ImuReactor
---   _line_angles[]   -- legacy 8-vector fallback (t="geometry" only)
---
--- Palette weather (mic_reactor.py) animates the reserved Air-tier slots:
---   sky(1), energy(2), drift_a(3), drift_b(4) — see palette.reserve_dynamic.
---
--- All state is updated on every host_comm tick (2 Hz) and rendered
--- at the display refresh rate (up to 20fps via frame.runloop).

local P    = require("display/primitives")
local PAL  = require("display/palette")
local TR   = require("display.transitions")
local math = math

local HAS_FRAME = (type(_G.frame) == "table")

local M = {}

-- Reserve the Air-tier dynamic slots (idempotent; mirrors themes.py
-- DYNAMIC_SLOTS so host palette frames land on the slots we draw with).
PAL.reserve_dynamic("sky",     PAL.accent_memory_dim, 1)
PAL.reserve_dynamic("energy",  PAL.accent_memory,     2)
PAL.reserve_dynamic("drift_a", PAL.border_subtle,     3)
PAL.reserve_dynamic("drift_b", PAL.border_subtle,     4)

-- ---------------------------------------------------------------------------
-- Constants
-- ---------------------------------------------------------------------------
local W, H       = 256, 256          -- display dimensions
local N_PARTICLES = 24
local N_LINES     = 8                -- legacy fallback field
local N_LINES_V2  = 12               -- curl-noise field (Line Field 2.0)
local CX, CY      = W/2, H/2

-- ---------------------------------------------------------------------------
-- State
-- ---------------------------------------------------------------------------
local _particles  = {}
local _line_angles = {}
local _line_field_v2 = nil   -- 12 {x1,y1,x2,y2} vectors from t="line_field"
local _anchor_key    = nil   -- Ghost Wake timing: current anchor identity
local _anchor_t0     = 0     -- ms when the current anchor first rendered
local _scatter_t   = 0
local _scatter_dur = 0
local _palette_target = {}    -- list of {idx, y, cb, cr} from mic reactor
local _geo_intensity  = 0.0
local _geo_mode       = "rotate"

-- Seed particles
for i = 1, N_PARTICLES do
  _particles[i] = {
    x   = CX + (math.random() - 0.5) * W * 0.8,
    y   = CY + (math.random() - 0.5) * H * 0.8,
    vx  = (math.random() - 0.5) * 0.8,
    vy  = (math.random() - 0.5) * 0.8,
    r   = math.random(1, 3),
    col = PAL.accent_memory,
  }
end

-- Seed line angles
for i = 1, N_LINES do
  _line_angles[i] = (i - 1) * math.pi / N_LINES
end

-- ---------------------------------------------------------------------------
-- Palette shift
-- ---------------------------------------------------------------------------

function M.apply_palette_shift(colors)
  -- colors: list of {idx, y, cb, cr}
  if not HAS_FRAME then return end
  for _, c in ipairs(colors) do
    frame.display.assign_color_ycbcr(
      c.idx,
      c.y  or 512,
      c.cb or 512,
      c.cr or 512
    )
  end
end

-- ---------------------------------------------------------------------------
-- Particle system
-- ---------------------------------------------------------------------------

function M.update_particles(intensity, mode)
  local scatter = (mode == "scatter")
  for _, p in ipairs(_particles) do
    if scatter then
      -- Explode outward from centre
      local dx = p.x - CX
      local dy = p.y - CY
      local dist = math.sqrt(dx*dx + dy*dy) + 0.1
      p.vx = p.vx + (dx/dist) * intensity * 4
      p.vy = p.vy + (dy/dist) * intensity * 4
    else
      -- Gentle drift with damping
      p.vx = p.vx * 0.92
      p.vy = p.vy * 0.92
    end
    p.x = p.x + p.vx
    p.y = p.y + p.vy
    -- Wrap around display edges
    if p.x < 0   then p.x = W end
    if p.x > W   then p.x = 0 end
    if p.y < 0   then p.y = H end
    if p.y > H   then p.y = 0 end
  end
end

function M.draw_particles()
  if not HAS_FRAME then return end
  for _, p in ipairs(_particles) do
    P.dot(p.x, p.y, p.r, p.col)
  end
end

-- ---------------------------------------------------------------------------
-- Line field (IMU-driven)
-- ---------------------------------------------------------------------------

function M.update_line_field(yaw_rate, intensity)
  local rotate_speed = yaw_rate * 0.008 * intensity
  for i = 1, N_LINES do
    _line_angles[i] = _line_angles[i] + rotate_speed
  end
end

function M.draw_line_field()
  if not HAS_FRAME then return end
  -- Line Field 2.0: prefer the streamed curl-noise vectors
  if _line_field_v2 then
    for _, v in ipairs(_line_field_v2) do
      frame.display.line(v[1], v[2], v[3], v[4], PAL.dynamic_color("sky"))
    end
    return
  end
  -- Legacy 8-vector radial fallback (no line_field frames received yet)
  local len = 40 + _geo_intensity * 60
  for i, angle in ipairs(_line_angles) do
    local x1 = CX + math.cos(angle) * len
    local y1 = CY + math.sin(angle) * len
    local x2 = CX - math.cos(angle) * len
    local y2 = CY - math.sin(angle) * len
    frame.display.line(
      math.floor(x1), math.floor(y1),
      math.floor(x2), math.floor(y2),
      PAL.text_ghost
    )
  end
end

-- ---------------------------------------------------------------------------
-- Line Field 2.0 handler (t="line_field")
-- msg.v is a flat array of 12*4 ints: {x1,y1,x2,y2, x1,y1,...} — one MTU
-- frame. Curl-noise + gyroscopic damping happen host-side (imu_reactor.py).
-- ---------------------------------------------------------------------------
function M.on_line_field(msg)
  local flat = msg and msg.v
  if type(flat) ~= "table" then return end
  local vecs = {}
  for i = 1, math.min(#flat, N_LINES_V2 * 4), 4 do
    vecs[#vecs + 1] = {
      math.floor(flat[i]     or CX),
      math.floor(flat[i + 1] or CY),
      math.floor(flat[i + 2] or CX),
      math.floor(flat[i + 3] or CY),
    }
  end
  _line_field_v2 = vecs
end

-- ---------------------------------------------------------------------------
-- Geometry command handler (called from host_comm)
-- ---------------------------------------------------------------------------

function M.on_geometry(cmd)
  _geo_mode      = cmd.mode      or "rotate"
  _geo_intensity = cmd.intensity or 0.0
  local yr = cmd.yaw_rate   or 0.0
  local pr = cmd.pitch_rate or 0.0
  M.update_particles(_geo_intensity, _geo_mode)
  M.update_line_field(yr, _geo_intensity)
end

-- ---------------------------------------------------------------------------
-- Ghost anchor renderer
-- ---------------------------------------------------------------------------

function M.render_world_anchor(card, now_ms)
  -- Ghost Wake (S2): text condenses from ambient jitter at the bottom of
  -- the display over SIG_GHOSTWAKE_MS, then settles at ghost-tier luma.
  if not HAS_FRAME then return end
  local summary = card.primary or ""
  local detail  = card.detail  or ""
  -- 22-char cap + rows 192/208/222 keep ghost text inside the circular
  -- safe chord (the old 210/226/242 rows clipped at the display edge)
  if #summary > 22 then summary = summary:sub(1, 21) .. "\xE2\x80\xA6" end
  if #detail  > 22 then detail  = detail:sub(1, 21) .. "\xE2\x80\xA6" end

  now_ms = now_ms or math.floor(os.clock() * 1000)
  local key = (card.anchor_id or "") .. "|" .. summary
  if key ~= _anchor_key then
    _anchor_key = key
    _anchor_t0  = now_ms
  end
  local A = require("display.animations")
  local t = math.min(1, (now_ms - _anchor_t0) / A.SIG_GHOSTWAKE_MS)

  TR.ghost_wake_text(CX, 192, "\xE2\x80\xA2 MEMORY ECHO \xE2\x80\xA2", "sm", t, _anchor_t0)
  TR.ghost_wake_text(CX, 208, summary, "sm", t, _anchor_t0 + 977)
  if detail ~= "" then
    TR.ghost_wake_text(CX, 222, detail, "sm", t, _anchor_t0 + 1954)
  end
end

-- ---------------------------------------------------------------------------
-- Synesthesia card renderer
-- ---------------------------------------------------------------------------

function M.render_synesthesia(card)
  -- 6-word VLM description in hero position, dream palette color
  if not HAS_FRAME then return end
  local desc = card.primary or ""
  P.text_center(CX, 100, "DREAM", "sm", PAL.accent_memory)
  -- Separator
  frame.display.line(64, 116, 192, 116, PAL.border_subtle)
  P.text_center(CX, 148, desc, "md", PAL.text_primary)
end

-- ---------------------------------------------------------------------------
-- SynesthesiaCard v2 (Halo Cinema v1, Phase 3)
-- Composes the 3-shape gestural sprite (bottom half, streamed separately as
-- a 128×128 TxSprite anchored at y=128) with the 6-word phrase (top half,
-- ghost tier). The sprite arrives via t="sprite" with anchor="bottom"; this
-- draws the text composition and the seam accent.
-- ---------------------------------------------------------------------------

function M.draw_synesthesia_v2(card)
  if not HAS_FRAME then return end
  local desc = card.primary or ""
  -- Top half: phrase at ghost tier (materials handles the ghost slot luma)
  local MAT = require("display.materials")
  MAT.draw_ghost_text(CX, 64, "DREAM", "sm", 0.7)
  P.text_center(CX, 96, desc, "md", PAL.text_primary)
  -- Seam: hairline where the sprite's half begins
  frame.display.line(48, 126, 208, 126, PAL.border_subtle)
  -- Bottom half belongs to the sprite (on_sprite draws it at y=128).
  -- If the sprite has not arrived yet, echo the dominant color as a hint.
  if not card.sprite_seen and card.dominant_color then
    frame.display.circle(CX, 190, 24, card.dominant_color, false)
  end
end

-- ---------------------------------------------------------------------------
-- Full dream frame (called from main runloop in dream mode)
-- ---------------------------------------------------------------------------

function M.draw_frame()
  if not HAS_FRAME then return end
  -- 1. Line field (background, drawn first)
  M.draw_line_field()
  -- 2. Particles (midground)
  M.draw_particles()
  -- NOTE: ghost anchor and synesthesia overlays are drawn by the card
  -- renderer when their respective cards are in the queue.
end

return M
