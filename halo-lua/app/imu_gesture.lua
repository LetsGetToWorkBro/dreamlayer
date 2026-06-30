--- app/imu_gesture.lua
--- IMU gesture classifier for Memoscape Halo.
---
--- Recognises five gestures from raw accelerometer samples:
---
---   NOD_SAVE      Forward + back head nod  → save the current memory
---   SHAKE_DISMISS Left/right head shake    → dismiss the current card
---   GLANCE_PEEK   Brief upward tilt        → peek at last card without full display
---   TILT_REVEAL   Sustained downward tilt  → reveal detail layer
---   DOUBLE_NOD    Two quick nods           → confirm / accept
---
--- Algorithm
--- ----------
--- Samples are fed one at a time via G:feed(ax, ay, az, now_ms).
--- Each axis is smoothed with an EMA, then a lightweight peak detector
--- watches for sign-flip crossings above a configurable threshold.
--- Crossing sequences are pattern-matched against a small state machine
--- per gesture class.  Each gesture fires at most once per COOLDOWN_MS.
---
--- Usage
--- -----
---   local G = require("app.imu_gesture").new({
---     on_gesture = function(name, confidence) ... end
---   })
---   -- in IMU callback or BLE rx loop:
---   G:feed(ax, ay, az, now_ms)
---
--- Tuning
--- ------
---   All thresholds live in DEFAULTS so you can tune without touching logic.
---
--- EMA seeding (for tests / replay)
--- ---------------------------------
---   Pass seed_ema_x, seed_ema_y, seed_ema_z in the opts table to start
---   each axis EMA pre-settled at a given value.  This lets test fixtures
---   deliver a gesture stream without a priming phase, avoiding spurious
---   threshold crossings before the gesture begins.

local M = {}

-- ---------------------------------------------------------------------------
-- Default config
-- ---------------------------------------------------------------------------

local DEFAULTS = {
  -- EMA smoothing factor (0 = no smoothing, 1 = frozen)
  ema_alpha         = 0.35,

  -- Axis peak threshold to count as a "crossing" (in raw g units * 100)
  threshold_nod     = 28,    -- Y-axis (pitch): nod up/down
  threshold_shake   = 28,    -- X-axis (yaw):   shake left/right
  threshold_tilt    = 20,    -- Z-axis (roll):  tilt

  -- Timing windows (ms)
  gesture_window_ms = 600,   -- max time for a full gesture pattern
  cooldown_ms       = 900,   -- min gap between same gesture fires
  hold_tilt_ms      = 400,   -- how long tilt must be held for TILT_REVEAL
  peek_max_ms       = 350,   -- max duration of a GLANCE_PEEK

  -- Confidence decay per crossing beyond minimum
  confidence_base   = 0.90,
  confidence_decay  = 0.05,
}

-- ---------------------------------------------------------------------------
-- EMA smoother
-- ---------------------------------------------------------------------------

local function new_ema(alpha, seed)
  -- seed: optional starting value (EMA is pre-settled, seeded=true)
  if seed ~= nil then
    return { alpha = alpha, value = seed, seeded = true }
  end
  return { alpha = alpha, value = 0.0, seeded = false }
end

local function ema_update(e, x)
  if not e.seeded then e.value = x; e.seeded = true
  else e.value = e.alpha * x + (1 - e.alpha) * e.value end
  return e.value
end

-- ---------------------------------------------------------------------------
-- Peak detector: emits +1 or -1 each time the smoothed signal crosses
-- +/- threshold in opposite direction from last crossing.
-- ---------------------------------------------------------------------------

local function new_peaks(threshold, seed_sign)
  -- seed_sign: optional, pre-set last_sign so the first real crossing is
  -- recorded immediately (used together with EMA seeding).
  return {
    threshold = threshold,
    last_sign = seed_sign or 0,
    crossings = {},
    _t        = {},
  }
end

local function peaks_feed(p, value, now_ms)
  local sign = 0
  if value >  p.threshold then sign =  1
  elseif value < -p.threshold then sign = -1 end

  if sign ~= 0 and sign ~= p.last_sign then
    p.last_sign = sign
    p.crossings[#p.crossings + 1] = sign
    p._t[#p._t + 1]               = now_ms
  end
end

local function peaks_recent(p, now_ms, window_ms)
  -- return crossings within the window as a simple array
  local out, out_t = {}, {}
  local cutoff = now_ms - window_ms
  for i, t in ipairs(p._t) do
    if t >= cutoff then
      out[#out+1]   = p.crossings[i]
      out_t[#out_t+1] = t
    end
  end
  -- prune old entries in-place
  p.crossings, p._t = out, out_t
  return out
end

-- ---------------------------------------------------------------------------
-- Pattern matchers
-- Returns confidence (0..1) if pattern matches, nil otherwise.
-- ---------------------------------------------------------------------------

-- NOD: Y axis — + then − (head tips forward then back)
local function match_nod(crossings)
  if #crossings >= 2 then
    for i = 1, #crossings - 1 do
      if crossings[i] > 0 and crossings[i+1] < 0 then
        return 0.90
      end
    end
  end
end

-- DOUBLE NOD: Y axis — + − + −  (two nod cycles)
local function match_double_nod(crossings)
  if #crossings >= 4 then
    if crossings[1] > 0 and crossings[2] < 0
    and crossings[3] > 0 and crossings[4] < 0 then
      return 0.92
    end
  end
end

-- SHAKE: X axis — − + −  or  + − + (at least 3 alternating crossings)
local function match_shake(crossings)
  if #crossings >= 3 then
    local ok = true
    for i = 2, #crossings do
      if crossings[i] == crossings[i-1] then ok = false; break end
    end
    if ok then return 0.88 end
  end
end

-- GLANCE_PEEK: Z axis — single positive crossing (brief upward tilt)
local function match_glance(crossings)
  if #crossings == 1 and crossings[1] > 0 then
    return 0.82
  end
end

-- TILT_REVEAL: Z axis — held negative value for hold_tilt_ms
-- Checked separately via sustained-value logic below.

-- ---------------------------------------------------------------------------
-- Gesture state machine
-- ---------------------------------------------------------------------------

local GESTURE = {
  NOD_SAVE      = "NOD_SAVE",
  SHAKE_DISMISS = "SHAKE_DISMISS",
  GLANCE_PEEK   = "GLANCE_PEEK",
  TILT_REVEAL   = "TILT_REVEAL",
  DOUBLE_NOD    = "DOUBLE_NOD",
}
M.GESTURE = GESTURE

function M.new(opts)
  opts = opts or {}
  local cfg = {}
  for k, v in pairs(DEFAULTS) do cfg[k] = opts[k] or v end

  -- Optional EMA seeds: start axes pre-settled to avoid spurious crossings
  -- in test/replay scenarios.  seed_ema_y > threshold means peaks_y already
  -- has last_sign = +1 so the first genuine negative crossing is captured.
  local sy = opts.seed_ema_y
  local sx = opts.seed_ema_x
  local sz = opts.seed_ema_z

  local self = {
    cfg         = cfg,
    on_gesture  = opts.on_gesture or function() end,
    _ema_x      = new_ema(cfg.ema_alpha, sx),
    _ema_y      = new_ema(cfg.ema_alpha, sy),
    _ema_z      = new_ema(cfg.ema_alpha, sz),
    -- pre-set last_sign to match seed so the first crossing direction is correct
    _peaks_x    = new_peaks(cfg.threshold_shake,
                    sx and (sx > cfg.threshold_shake and 1 or (sx < -cfg.threshold_shake and -1 or 0)) or 0),
    _peaks_y    = new_peaks(cfg.threshold_nod,
                    sy and (sy > cfg.threshold_nod   and 1 or (sy < -cfg.threshold_nod   and -1 or 0)) or 0),
    _peaks_z    = new_peaks(cfg.threshold_tilt,
                    sz and (sz > cfg.threshold_tilt  and 1 or (sz < -cfg.threshold_tilt  and -1 or 0)) or 0),
    _cooldowns  = {},   -- gesture_name -> last_fired_ms (nil means never fired)
    -- tilt-hold tracking
    _tilt_start  = nil,
    _tilt_active = false,
    -- glance tracking
    _glance_start  = nil,
    _glance_active = false,
  }
  setmetatable(self, { __index = M })
  return self
end

-- ---------------------------------------------------------------------------
-- Feed a single sample
-- ---------------------------------------------------------------------------

function M:feed(ax, ay, az, now_ms)
  local sx = ema_update(self._ema_x, ax)
  local sy = ema_update(self._ema_y, ay)
  local sz = ema_update(self._ema_z, az)

  peaks_feed(self._peaks_x, sx, now_ms)
  peaks_feed(self._peaks_y, sy, now_ms)
  peaks_feed(self._peaks_z, sz, now_ms)

  local win = self.cfg.gesture_window_ms
  local cx  = peaks_recent(self._peaks_x, now_ms, win)
  local cy  = peaks_recent(self._peaks_y, now_ms, win)
  local cz  = peaks_recent(self._peaks_z, now_ms, win)

  -- DOUBLE_NOD (check before single NOD to avoid shadowing)
  local conf_dn = match_double_nod(cy)
  if conf_dn then
    if self:_fire(GESTURE.DOUBLE_NOD, conf_dn, now_ms) then
      self._peaks_y.crossings, self._peaks_y._t = {}, {}
      return
    end
  end

  -- NOD_SAVE
  -- Do NOT clear peaks_y here: subsequent crossings must remain visible so
  -- that a double-nod can still be detected after the first nod fires.
  local conf_nod = match_nod(cy)
  if conf_nod then
    self:_fire(GESTURE.NOD_SAVE, conf_nod, now_ms)
  end

  -- SHAKE_DISMISS
  local conf_shk = match_shake(cx)
  if conf_shk then
    if self:_fire(GESTURE.SHAKE_DISMISS, conf_shk, now_ms) then
      self._peaks_x.crossings, self._peaks_x._t = {}, {}
      return
    end
  end

  -- TILT_REVEAL: Z sustained negative
  if sz < -self.cfg.threshold_tilt then
    if not self._tilt_active then
      self._tilt_active = true
      self._tilt_start  = now_ms
    elseif (now_ms - self._tilt_start) >= self.cfg.hold_tilt_ms then
      if self:_fire(GESTURE.TILT_REVEAL, 0.85, now_ms) then
        self._tilt_active = false
        self._peaks_z.crossings, self._peaks_z._t = {}, {}
        return
      end
    end
  else
    self._tilt_active = false
    self._tilt_start  = nil
  end

  -- GLANCE_PEEK: Z single brief positive crossing, not sustained
  local conf_gl = match_glance(cz)
  if conf_gl then
    if not self._glance_active then
      self._glance_active = true
      self._glance_start  = now_ms
    end
  else
    if self._glance_active then
      local dur = now_ms - (self._glance_start or now_ms)
      if dur <= self.cfg.peek_max_ms then
        self:_fire(GESTURE.GLANCE_PEEK, 0.82, now_ms)
      end
      self._glance_active = false
      self._glance_start  = nil
      self._peaks_z.crossings, self._peaks_z._t = {}, {}
    end
  end
end

-- ---------------------------------------------------------------------------
-- Fire a gesture if not on cooldown.
-- Returns true if the gesture was fired.
-- ---------------------------------------------------------------------------

function M:_fire(name, confidence, now_ms)
  local last = self._cooldowns[name]
  -- nil means this gesture has never fired: always allow the first fire.
  if last and (now_ms - last) < self.cfg.cooldown_ms then return false end
  self._cooldowns[name] = now_ms
  self.on_gesture(name, confidence)
  return true
end

-- ---------------------------------------------------------------------------
-- Reset all state (e.g. on reconnect)
-- ---------------------------------------------------------------------------

function M:reset()
  self._ema_x    = new_ema(self.cfg.ema_alpha)
  self._ema_y    = new_ema(self.cfg.ema_alpha)
  self._ema_z    = new_ema(self.cfg.ema_alpha)
  self._peaks_x  = new_peaks(self.cfg.threshold_shake)
  self._peaks_y  = new_peaks(self.cfg.threshold_nod)
  self._peaks_z  = new_peaks(self.cfg.threshold_tilt)
  self._cooldowns    = {}
  self._tilt_active  = false
  self._glance_active = false
end

return M
