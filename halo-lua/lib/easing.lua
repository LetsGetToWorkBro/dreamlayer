-- easing.lua : deterministic easing functions, t in [0,1]
--
-- Halo Cinema v1 additions:
--   out_expo      — signature entrance curve (Iris Bloom ring collapse)
--   in_out_cubic  — symmetric travel (Memory Comet path, jitter decay)
--   out_back      — subtle overshoot, capped at ~4% (never for text)
--   perlin1d      — Perlin-noise-lite value noise for Ghost Wake jitter;
--                   seed with monotonic time so runs never repeat.
local M = {}
function M.linear(t) return t end
function M.in_quad(t) return t*t end
function M.out_quad(t) return t*(2-t) end
function M.in_out_quad(t)
  if t < 0.5 then return 2*t*t else return -1 + (4 - 2*t)*t end
end
function M.out_cubic(t) t = t - 1; return t*t*t + 1 end
function M.in_out_sine(t) return -(math.cos(math.pi*t) - 1) / 2 end

function M.out_expo(t)
  if t >= 1 then return 1 end
  return 1 - 2 ^ (-10 * t)
end

function M.in_out_cubic(t)
  if t < 0.5 then return 4*t*t*t end
  t = 2*t - 2
  return 1 + t*t*t / 2
end

-- Overshoot factor tuned so the peak value stays <= 1.04 (4% budget).
local BACK_S = 0.7
function M.out_back(t)
  t = t - 1
  return 1 + t*t*((BACK_S + 1)*t + BACK_S)
end

-- ---------------------------------------------------------------------------
-- Meridian Lumen: closed-form damped spring (docs/cinema_v2/lumen.md).
-- x(t) = 1 - e^(-zeta*omega*t) * (cos(wd*t) + (zeta*omega/wd)*sin(wd*t)),
-- wd = omega*sqrt(1 - zeta^2). A pure function of t — no integration
-- state — so sequences are deterministic and golden-safe. zeta/omega
-- values live in display/animations.lua (SPRING_*); callers pass them.
-- First-peak overshoot is exp(-zeta*pi/sqrt(1-zeta^2)): the shipped
-- zetas keep it under SPRING_OVERSHOOT_MAX (asserted in tests).
-- ---------------------------------------------------------------------------
function M.spring(t, zeta, omega)
  if t <= 0 then return 0 end
  if t >= 1 then return 1 end
  zeta  = zeta  or 0.85
  omega = omega or 7.4
  if zeta >= 0.999 then zeta = 0.999 end
  local wd    = omega * math.sqrt(1 - zeta * zeta)
  local decay = math.exp(-zeta * omega * t)
  return 1 - decay * (math.cos(wd * t) + (zeta * omega / wd) * math.sin(wd * t))
end

-- Anticipation: the first `frac` of the motion pulls BACK (to -amt at the
-- window's midpoint, returning to 0 at its end), then the remaining time
-- runs the main in_out_cubic flight. Never applied to text (the out_back
-- rule above extends: anticipation moves geometry heads, not glyphs).
function M.anticipate(t, frac, amt)
  frac = frac or 0.12
  amt  = amt  or 1.0
  if t <= 0 then return 0 end
  if t >= 1 then return 1 end
  if t < frac then
    return -amt * math.sin(math.pi * (t / frac))
  end
  return M.in_out_cubic((t - frac) / (1 - frac))
end

-- ---------------------------------------------------------------------------
-- Perlin-noise-lite (1D value noise with smoothstep interpolation).
-- Deterministic for a given x; callers seed by offsetting x with monotonic
-- time and a per-element salt:  easing.perlin1d(now_ms * 0.004 + i * 7.13)
-- Returns a value in [-1, 1].
-- ---------------------------------------------------------------------------
local function hash(n)
  n = math.floor(n) % 289
  local v = (n * 34 + 1) * n % 289
  return (v / 144.5) - 1.0   -- map [0,289) -> [-1,1)
end

function M.perlin1d(x)
  local x0 = math.floor(x)
  local f  = x - x0
  local u  = f * f * (3 - 2 * f)      -- smoothstep fade
  local a, b = hash(x0), hash(x0 + 1)
  return a + (b - a) * u
end

return M
