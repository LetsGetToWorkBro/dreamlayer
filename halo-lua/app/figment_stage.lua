-- app/figment_stage.lua
-- The fixed stage: the only thing that ever runs a user-authored behavior.
--
-- Reality Compiler v2 never ships code to Halo. Behaviors arrive as
-- *figments* — declarative scene-machine tables (see host-side
-- reality_compiler/v2/figment.py for the schema) — and this module is the
-- single, reviewed interpreter that runs them. Whitelist by construction:
-- a figment can show text lines, count down/up, keep bounded counters,
-- pulse a color, and emit small rate-limited tags to the host. There is
-- no way for figment data to name a function, touch os/io/network, or
-- exceed the display/BLE budgets below.
--
-- Host messages (ble/message_types.lua, mirrored in v2/transport.py):
--   figment_put    {id, figment, hash}  -> stored inactive, ack'd
--   figment_swap   {id}                 -> becomes active between ticks
--   figment_revoke {id}                 -> stopped + cleared, ack'd
--   figment_text   {id, text}           -> fills the {slot} token
--
-- Dynamic clamps (defense in depth — the host proves these statically
-- before signing, the stage enforces them again at runtime):
--   MAX_SCENES/LINES/TEXT_LEN on load; counter saturation on every op;
--   emit token bucket (burst 5, refill 1/s); pulse rate hard-capped.

local MT = require("ble.message_types")

local M = {}

-- Budgets — keep in lockstep with v2/figment.py
local MAX_SCENES     = 32
local MAX_COUNTERS   = 8
local MAX_LINES      = 5
local MAX_TEXT_LEN   = 24
local MAX_PULSE_HZ   = 4.0
local MIN_SCENE_SEC  = 0.5
local EMIT_BURST     = 5
local EMIT_REFILL    = 1.0
local BATTERY_COOLDOWN_SEC = 60.0

-- Bound device APIs (main.lua calls M.bind before the tick loop)
local _display = nil   -- { text=fn(str,x,y,opts), clear=fn(), show=fn() }
local _send    = nil   -- fn(envelope_table) -> host
local _battery = nil   -- fn() -> percent or nil
local _random  = math.random

-- Stage state
local _stored  = {}    -- id -> figment table (inactive library)
local _active  = nil   -- the running figment
local _st      = nil   -- runtime state for _active

-- ---------------------------------------------------------------------------
-- Load-time structural clamps
-- ---------------------------------------------------------------------------

local function _count(t)
  local n = 0
  for _ in pairs(t or {}) do n = n + 1 end
  return n
end

local function _clamp_ok(fig)
  if type(fig) ~= "table" or type(fig.scenes) ~= "table" then return false end
  if _count(fig.scenes) == 0 or _count(fig.scenes) > MAX_SCENES then return false end
  if _count(fig.counters) > MAX_COUNTERS then return false end
  if not fig.initial or not fig.scenes[fig.initial] then return false end
  for _, scene in pairs(fig.scenes) do
    if _count(scene.lines) > MAX_LINES then return false end
    if scene.duration_sec and scene.duration_sec < MIN_SCENE_SEC then return false end
    if scene.pulse and (scene.pulse.rate_hz or 0) > MAX_PULSE_HZ then return false end
  end
  return true
end

-- ---------------------------------------------------------------------------
-- Runtime state
-- ---------------------------------------------------------------------------

local function _enter(scene_id)
  local scene = _active.scenes[scene_id]
  _st.last_elapsed = _st.elapsed or 0
  _st.current  = scene_id
  _st.elapsed  = 0
  if scene.duration_range then
    local lo, hi = scene.duration_range[1], scene.duration_range[2]
    _st.duration = lo + _random() * (hi - lo)
  else
    _st.duration = scene.duration_sec  -- may be nil (event-only scene)
  end
end

local function _start(fig)
  _active = fig
  _st = {
    counters = {},
    slot = "",
    tokens = EMIT_BURST,
    battery_cd = 0,
    ended = false,
  }
  for name, decl in pairs(fig.counters or {}) do
    _st.counters[name] = decl.start or 0
  end
  _enter(fig.initial)
end

local function _stop()
  _active, _st = nil, nil
end

-- ---------------------------------------------------------------------------
-- Transitions (mirror interpreter.py exactly)
-- ---------------------------------------------------------------------------

local function _apply_ops(ops)
  for _, op in ipairs(ops or {}) do
    local decl = (_active.counters or {})[op.counter]
    if decl then
      local cur = _st.counters[op.counter] or 0
      local amount = op.amount or 1
      if op.op == "inc" then cur = cur + amount
      elseif op.op == "dec" then cur = cur - amount
      else cur = amount end
      local lo, hi = decl.lo or 0, decl.hi or 9999
      if cur < lo then cur = lo end
      if cur > hi then cur = hi end
      _st.counters[op.counter] = cur
    end
  end
end

local function _emit(tag)
  if _st.tokens >= 1.0 then
    _st.tokens = _st.tokens - 1.0
    if _send then
      _send({ t = MT.FIGMENT_EVENT, id = _active.id, tag = tag })
    end
  end
  -- over-budget emits are dropped silently: the flood never reaches BLE
end

local function _guard_ok(when)
  if not when then return true end
  local val = _st.counters[when.counter] or 0
  if when.cmp == "ge" then return val >= when.value end
  if when.cmp == "le" then return val <= when.value end
  return val == when.value
end

local function _take(t)
  _apply_ops(t.counter_ops)
  if t.emit then _emit(t.emit) end
  if t.target == "@end" then
    _st.ended = true
    _st.last_elapsed = _st.elapsed
  elseif t.target == "@self" then
    _enter(_st.current)
  else
    _enter(t.target)
  end
end

local function _timeout()
  local scene = _active.scenes[_st.current]
  for _, t in ipairs(scene.on_timeout or {}) do
    if _guard_ok(t.when) then
      _take(t)
      return
    end
  end
  _st.ended = true
end

-- ---------------------------------------------------------------------------
-- Events
-- ---------------------------------------------------------------------------

-- ev: "single" | "double" | "long" | "imu_tap" | "ble" | "ble:<n>" |
--     "text" | "battery_low"
function M.on_event(ev, text)
  if not _active or _st.ended then return false end
  if ev == "text" and text then
    _st.slot = string.sub(tostring(text), 1, MAX_TEXT_LEN)
  end
  local scene = _active.scenes[_st.current]
  local t = (scene.on or {})[ev]
  if not t and string.sub(ev, 1, 4) == "ble:" then
    t = (scene.on or {})["ble"]
  end
  if not t then return false end
  _take(t)
  return true
end

-- ---------------------------------------------------------------------------
-- Tick
-- ---------------------------------------------------------------------------

local function _fmt_clock(secs)
  secs = math.max(0, math.ceil(secs))
  if secs >= 60 then
    return string.format("%d:%02d", math.floor(secs / 60), secs % 60)
  end
  return tostring(secs)
end

local function _resolve(scene, content)
  local remaining = 0
  if _st.duration then remaining = math.max(0, _st.duration - _st.elapsed) end
  -- {elapsed} runs only in ticking scenes; frozen otherwise (stopwatch
  -- STOPPED, reaction result) — same rule as interpreter.py
  local elapsed = scene.tick and _st.elapsed or (_st.last_elapsed or 0)
  local out = content
  out = string.gsub(out, "{remaining}", _fmt_clock(remaining))
  out = string.gsub(out, "{remaining_s}", tostring(math.ceil(remaining)))
  out = string.gsub(out, "{elapsed}", _fmt_clock(elapsed))
  out = string.gsub(out, "{elapsed_ms}", tostring(math.floor(elapsed * 1000)))
  out = string.gsub(out, "{slot}", _st.slot or "")
  for name, val in pairs(_st.counters) do
    out = string.gsub(out, "{count:" .. name .. "}", tostring(val))
  end
  return string.sub(out, 1, MAX_TEXT_LEN)
end

local function _render()
  if not _display then return end
  _display.clear()
  if _st.ended then
    _display.show()
    return
  end
  local scene = _active.scenes[_st.current]

  local pulse_color = nil
  if scene.pulse and _st.duration then
    local remaining = _st.duration - _st.elapsed
    if remaining <= scene.pulse.window_sec then
      local rate = math.min(scene.pulse.rate_hz or 2.0, MAX_PULSE_HZ)
      local phase = _st.elapsed * rate
      if math.floor(phase * 2) % 2 == 0 then
        pulse_color = scene.pulse.color
      end
    end
  end

  for _, line in ipairs(scene.lines or {}) do
    local row = math.min(line.row or 0, MAX_LINES - 1)
    local y = 40 + row * 44   -- 5 rows inside the 256px circular safe area
    _display.text(_resolve(scene, line.content or ""), 24, y, {
      size = line.size or "md",
      color = line.color or "text_primary",
      pulse = pulse_color,
    })
  end
  _display.show()
end

-- Advance dt seconds. Called from main.lua's tick loop; rendering is
-- capped by the loop cadence, pulse phase is computed from scene time.
function M.tick(dt)
  if not _active or _st.ended then return end
  dt = dt or 0.05

  _st.tokens = math.min(EMIT_BURST, _st.tokens + dt * EMIT_REFILL)

  -- battery watch (cooldown so a low battery can't spam the scene graph)
  _st.battery_cd = math.max(0, (_st.battery_cd or 0) - dt)
  if _active.battery_below and _battery and _st.battery_cd <= 0 then
    local level = _battery()
    if level and level < _active.battery_below then
      _st.battery_cd = BATTERY_COOLDOWN_SEC
      M.on_event("battery_low")
    end
  end

  if not (_active and _st) or _st.ended then return end

  _st.elapsed = _st.elapsed + dt
  -- at most a handful of timeouts per tick; each consumes >= MIN_SCENE_SEC
  -- of scene time, so this loop is bounded by dt / MIN_SCENE_SEC + 1
  local hops = 0
  while _st.duration and _st.elapsed >= _st.duration
        and not _st.ended and hops < 8 do
    local overshoot = _st.elapsed - _st.duration
    _timeout()
    if _st.ended then break end
    _st.elapsed = _st.elapsed + overshoot
    hops = hops + 1
  end

  _render()
end

-- ---------------------------------------------------------------------------
-- Host message handlers
-- ---------------------------------------------------------------------------

local function _ack(id, ok, hash)
  if _send then
    _send({ t = MT.FIGMENT_ACK, id = id, ok = ok and true or false,
            hash = hash })
  end
end

local function _on_put(msg)
  local fig = msg.figment
  if fig and _clamp_ok(fig) then
    fig.id = msg.id or fig.id
    _stored[fig.id] = fig
    _ack(fig.id, true, msg.hash)
  else
    _ack(msg.id, false, msg.hash)
  end
end

local function _on_swap(msg)
  local fig = _stored[msg.id]
  if fig then
    _start(fig)              -- between ticks by construction: handlers run
    _ack(msg.id, true)       -- from the BLE dispatch, never mid-_render
  else
    _ack(msg.id, false)
  end
end

local function _on_revoke(msg)
  _stored[msg.id] = nil
  if _active and _active.id == msg.id then
    _stop()
    if _display then _display.clear(); _display.show() end
  end
  _ack(msg.id, true)
end

local function _on_text(msg)
  if _active and (_active.id == msg.id or msg.id == nil) then
    M.on_event("text", msg.text)
  end
end

-- ---------------------------------------------------------------------------
-- Wiring
-- ---------------------------------------------------------------------------

-- host_comm: the ble/host_comm.lua module (for handler registration)
function M.register(host_comm)
  host_comm.register(MT.FIGMENT_PUT,    _on_put)
  host_comm.register(MT.FIGMENT_SWAP,   _on_swap)
  host_comm.register(MT.FIGMENT_REVOKE, _on_revoke)
  host_comm.register(MT.FIGMENT_TEXT,   _on_text)
end

-- deps: { display = {text,clear,show}, send = fn(tbl),
--         battery = fn() -> pct, random = fn() -> [0,1) }
function M.bind(deps)
  _display = deps.display or _display
  _send    = deps.send or _send
  _battery = deps.battery or _battery
  _random  = deps.random or _random
end

function M.active_id()
  return _active and _active.id or nil
end

function M.is_running()
  return _active ~= nil and not _st.ended
end

-- test/emulator introspection
function M._state()
  return _st, _active
end

return M
