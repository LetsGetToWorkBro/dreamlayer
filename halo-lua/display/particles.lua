--- display/particles.lua
--- Meridian Lumen: one pooled, budgeted particle system for the hero
--- moments (docs/cinema_v2/lumen.md) — save-confirm bursts, promise
--- shatter shards, testimony tear spits, and the dream-door starfield
--- streaks. AIR tier: never information-bearing; every reading a hero
--- moment carries lives in the geometry underneath it.
---
--- Physics is CLOSED-FORM: a particle's position is a pure function of
--- (now_ms - t0), so sequences are deterministic and golden-safe.
--- Velocities derive from easing.perlin1d(seed + i*7.13) — pass the same
--- seed, get the same burst. No math.random anywhere in this module
--- (dream weather keeps its own random particles and its own golden
--- carve-out; this pool is for the deterministic hero paths).
---
--- Budget: at most animations.PARTICLE_BUDGET live particles. A spawn
--- that would exceed it evicts the oldest first — hero moments win over
--- leftovers, and the worst frame is bounded.
---
--- Fading is honest 4bpp: no alpha — dots shrink 2px -> 1px -> gone and
--- streaks shorten. reduce_motion: spawns are no-ops (each hero moment's
--- reduce path is its existing static state).
---
--- Public API:
---   PT.burst(cx, cy, n, opts)    radial burst    opts: t0, seed, color,
---                                                speed, ttl_ms
---   PT.shards(deg, n, opts)      inward shards from rim angle deg
---   PT.streaks(n, opts)          starfield warp  opts: t0, seed, color,
---                                                ttl_ms, reverse
---   PT.tick(now_ms [, ox, oy])   advance + draw (ox/oy: parallax offset)
---   PT.live_count() / PT.clear()

local A  = require("display.animations")
local P  = require("display.palette")
local E  = require("lib.easing")
local TR = require("display.transitions")

local HAS_FRAME = (type(_G.frame) == "table")

local M = {}

local CX, CY = 128, 128

local _pool = {}   -- live particles, spawn order

local function fl(n) return math.floor(n + 0.5) end

local function evict_for(n)
  local excess = (#_pool + n) - A.PARTICLE_BUDGET
  while excess > 0 and #_pool > 0 do
    table.remove(_pool, 1)
    excess = excess - 1
  end
end

--- Radial burst from (cx, cy): n dots fly outward on deterministic
--- spokes with per-dot perlin speed variation, shrinking as they age.
function M.burst(cx, cy, n, opts)
  if TR.reduce_motion() then return end
  opts = opts or {}
  n = math.min(n or A.BURST_N, A.PARTICLE_BUDGET)
  evict_for(n)
  local seed  = opts.seed or 0
  local speed = opts.speed or A.BURST_SPEED
  local ttl   = opts.ttl_ms or A.BURST_MS
  for i = 1, n do
    local ang = 2 * math.pi * (i - 1) / n
              + E.perlin1d(seed + i * 7.13) * 0.35
    local sp  = speed * (0.7 + 0.3 * math.abs(E.perlin1d(seed + i * 13.7)))
    _pool[#_pool + 1] = {
      kind = "dot",
      x0 = cx or CX, y0 = cy or CY,
      vx = math.cos(ang) * sp / 1000,   -- px per ms
      vy = math.sin(ang) * sp / 1000,
      t0 = opts.t0 or 0, ttl = ttl,
      color = opts.color or P.accent_success,
    }
  end
end

--- Shatter shards: n fragments thrown off the rim at angle `deg`,
--- falling inward (a broken promise drops out of the sky, it does not
--- fly away). Deterministic per (deg, seed).
function M.shards(deg, n, opts)
  if TR.reduce_motion() then return end
  opts = opts or {}
  n = math.min(n or A.SHARD_N, A.PARTICLE_BUDGET)
  evict_for(n)
  local seed  = (opts.seed or 0) + fl((deg or 0) * 53)
  local speed = opts.speed or A.SHARD_SPEED
  local ttl   = opts.ttl_ms or A.SHARD_MS
  local rad   = math.rad(deg or 0)
  local ox, oy = CX + A.MER_PROMISE_R * math.cos(rad),
                 CY + A.MER_PROMISE_R * math.sin(rad)
  -- inward unit vector plus perpendicular scatter
  local ix, iy = -math.cos(rad), -math.sin(rad)
  local px, py = -math.sin(rad),  math.cos(rad)
  for i = 1, n do
    local scatter = E.perlin1d(seed + i * 7.13) * 0.8
    local sp = speed * (0.6 + 0.4 * math.abs(E.perlin1d(seed + i * 13.7)))
    _pool[#_pool + 1] = {
      kind = "dot",
      x0 = ox, y0 = oy,
      vx = (ix + px * scatter) * sp / 1000,
      vy = (iy + py * scatter) * sp / 1000,
      t0 = opts.t0 or 0, ttl = ttl,
      color = opts.color or P.status_paused,
    }
  end
end

--- Starfield warp streaks (the dream door): n radial lines that
--- accelerate outward (or rush inward when `reverse`), length growing
--- with speed. Same terrain, hyperspace light.
function M.streaks(n, opts)
  if TR.reduce_motion() then return end
  opts = opts or {}
  n = math.min(n or A.WARP_STREAKS, A.PARTICLE_BUDGET)
  evict_for(n)
  local seed = opts.seed or 0
  local ttl  = opts.ttl_ms or A.MER_DREAM_ENTER_MS
  for i = 1, n do
    local ang = 2 * math.pi * (i - 1) / n
              + E.perlin1d(seed + i * 7.13) * 0.2
    _pool[#_pool + 1] = {
      kind = "streak",
      ang = ang,
      r0 = 24 + 60 * math.abs(E.perlin1d(seed + i * 13.7)),
      t0 = opts.t0 or 0, ttl = ttl,
      reverse = opts.reverse or false,
      color = opts.color or P.accent_memory_dim,
    }
  end
end

local function draw_dot(pt, age, life, ox, oy)
  local x = pt.x0 + pt.vx * age + (ox or 0)
  local y = pt.y0 + pt.vy * age + (oy or 0)
  local r = (life < 0.5) and 1 or 2       -- honest fade: shrink, no alpha
  frame.display.circle(fl(x), fl(y), r, pt.color, true)
end

local function draw_streak(pt, age, life, ox, oy)
  -- closed-form acceleration: radius advances with t^2 (hyperspace ramp)
  local t = 1 - life
  if pt.reverse then t = life end
  local r   = pt.r0 + (A.MER_TRACK_R - pt.r0) * t * t
  local len = A.WARP_STREAK_LEN * t * (life < 0.4 and life / 0.4 or 1)
  if len < 1 then return end
  local ca, sa = math.cos(pt.ang), math.sin(pt.ang)
  frame.display.line(
    fl(CX + r * ca + (ox or 0)),         fl(CY + r * sa + (oy or 0)),
    fl(CX + (r + len) * ca + (ox or 0)), fl(CY + (r + len) * sa + (oy or 0)),
    pt.color)
end

--- Advance and draw every live particle. Expired particles cull here.
--- ox/oy: the AIR-depth parallax offset (parallax.offset("air")).
function M.tick(now_ms, ox, oy)
  if #_pool == 0 then return end
  local keep = {}
  for _, pt in ipairs(_pool) do
    local age = (now_ms or 0) - pt.t0
    if age >= 0 and age < pt.ttl then
      local life = 1 - age / pt.ttl       -- 1 fresh -> 0 expired
      if HAS_FRAME then
        if pt.kind == "streak" then
          draw_streak(pt, age, life, ox, oy)
        else
          draw_dot(pt, age, life, ox, oy)
        end
      end
      keep[#keep + 1] = pt
    end
  end
  _pool = keep
end

function M.live_count() return #_pool end

function M.clear() _pool = {} end

return M
