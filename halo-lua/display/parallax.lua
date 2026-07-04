--- display/parallax.lua
--- Meridian Lumen: IMU-coupled depth (docs/cinema_v2/lumen.md). Ambient
--- HUD layers shift a few pixels *against* head motion, so the horizon
--- reads as anchored in the world and the rings float above it; when the
--- head stops, the layers spring home with a small inertial overshoot.
--- Runs entirely on-device off frame.imu_data() — no BLE round-trip, so
--- it works at the full 20fps tick.
---
--- Depth classes (offsets scale by depth; information NEVER moves):
---   lock  0px   all text, testimony thread, confidence dots, privacy
---   rim   ±1px  horizon track / marks / notch (world-anchored day)
---   ring  ±2px  focus & landing rings, bloom halos
---   air   ±3px  particles, line fields, premonitions
---
--- Failure model: frame.imu_data absent or erroring (emulator, CI, older
--- firmware) -> permanent zero offsets. reduce_motion -> zero offsets.
--- freeze(true) (privacy slam) -> offsets snap to zero — the world grips.
---
--- Worst case geometry: rim mark tip r=110 + 1px = 111 < SAFE_RADIUS=112
--- (halo-lua/lib/constants.lua) — parallax can never push content out of
--- the safe circle.
---
--- Public API:
---   parallax.tick(now_ms)          sample IMU, advance offsets (1/frame)
---   parallax.offset(depth) -> x,y  current offset for a depth class
---   parallax.freeze(flag)          privacy grip
---   parallax.reset()               test hook

local A  = require("display.animations")
local E  = require("lib.easing")
local TR = require("display.transitions")

local M = {}

local TICK_S    = 0.05    -- fixed-step: main.lua ticks at 50ms
local RATE_EPS  = 8       -- deg/s below which the head counts as still

local _prev      = nil    -- last {pitch, roll} sample
local _ema_x     = 0      -- EMA'd horizontal rate (deg/s)
local _ema_y     = 0
local _x, _y     = 0, 0   -- current air-depth offset (px, float)
local _return    = nil    -- { t0=, fx=, fy= } spring-home flight
local _frozen    = false
local _last_ms   = nil

local function clamp(v, lo, hi) return math.max(lo, math.min(hi, v)) end

local function read_imu()
  if type(_G.frame) ~= "table" or type(frame.imu_data) ~= "function" then
    return nil
  end
  local ok, imu = pcall(frame.imu_data)
  if not ok or type(imu) ~= "table" then return nil end
  local pitch = tonumber(imu.pitch)
  local roll  = tonumber(imu.roll or imu.yaw or imu.heading)
  if not pitch then return nil end
  return pitch, roll or 0
end

function M.tick(now_ms)
  if _frozen or TR.reduce_motion() then
    _x, _y, _return, _prev = 0, 0, nil, nil
    return
  end

  local pitch, roll = read_imu()
  if not pitch then
    _x, _y, _return, _prev = 0, 0, nil, nil
    return
  end

  if _prev then
    -- pose delta -> rate (deg/s), EMA-smoothed (same idiom as imu_gesture)
    local rx = (roll  - _prev.roll)  / TICK_S
    local ry = (pitch - _prev.pitch) / TICK_S
    _ema_x = _ema_x + A.PAR_EMA_ALPHA * (rx - _ema_x)
    _ema_y = _ema_y + A.PAR_EMA_ALPHA * (ry - _ema_y)
  end
  _prev    = { pitch = pitch, roll = roll }
  _last_ms = now_ms

  local moving = math.abs(_ema_x) > RATE_EPS or math.abs(_ema_y) > RATE_EPS
  local max_px = A.PAR_MAX_PX.air

  if moving then
    -- layers shift AGAINST the head: PAR_RATE_GAIN px per 100 deg/s
    _return = nil
    _x = clamp(-_ema_x * A.PAR_RATE_GAIN / 100, -max_px, max_px)
    _y = clamp(-_ema_y * A.PAR_RATE_GAIN / 100, -max_px, max_px)
  elseif (_x ~= 0 or _y ~= 0) then
    -- the head stopped: spring home with a small inertial overshoot
    if not _return then
      _return = { t0 = now_ms, fx = _x, fy = _y }
    end
    local t = clamp((now_ms - _return.t0) / A.PAR_RETURN_MS, 0, 1)
    local s = E.spring(t, A.PAR_SPRING_ZETA, A.SPRING_OMEGA)
    _x = _return.fx * (1 - s)
    _y = _return.fy * (1 - s)
    if t >= 1 then
      _x, _y, _return = 0, 0, nil
    end
  end
end

local DEPTH_SCALE = nil
local function depth_scale(depth)
  if not DEPTH_SCALE then
    local air = A.PAR_MAX_PX.air
    DEPTH_SCALE = {
      lock = 0,
      rim  = A.PAR_MAX_PX.rim  / air,
      ring = A.PAR_MAX_PX.ring / air,
      air  = 1,
    }
  end
  return DEPTH_SCALE[depth] or 0
end

--- Offset for a depth class. Returns floats; callers floor after adding.
function M.offset(depth)
  local s = depth_scale(depth or "lock")
  if s == 0 then return 0, 0 end
  return _x * s, _y * s
end

--- Privacy grip: while frozen every depth reads (0, 0) instantly.
function M.freeze(flag)
  _frozen = not not flag
  if _frozen then
    _x, _y, _return, _prev = 0, 0, nil, nil
  end
end

function M.reset()
  _prev, _ema_x, _ema_y = nil, 0, 0
  _x, _y, _return, _frozen, _last_ms = 0, 0, nil, false, nil
end

return M
