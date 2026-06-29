-- main.lua : Halo boot entry point. Autoruns on device.
-- Wires modules, registers callbacks, runs the event loop.
--
-- NOTE ON REAL HALO API (2026-06)
-- Halo does NOT expose settable callback fields on halo.button / halo.imu.
-- All inbound events (button presses, IMU taps, host messages) arrive via
-- halo.bluetooth.receive() polled each tick.  The host encodes them as
-- JSON envelopes: { "t": "button", "ev": "single" } etc.
-- See ble/host_comm.lua for the full opcode table.
local time      = require("system.time")
local logging   = require("system.logging")
local settings  = require("system.settings")
local power     = require("system.power")
local renderer  = require("display.renderer")
local anim      = require("display.animations")
local scheduler = require("capture.scheduler")
local camera    = require("capture.camera")
local microphone= require("capture.microphone")
local activity  = require("capture.activity")
local host_comm = require("ble.host_comm")
local state_machine = require("app.state_machine")
local session   = require("app.session")
local E         = require("app.events")

-- `halo` is the global injected by the Halo runtime.
-- On emulator it is mocked.  On device it is the real SDK table.
local halo = _G.halo or {}

-- ---------------------------------------------------------------------------
-- Capability assertions — log loudly rather than silently missing APIs
-- ---------------------------------------------------------------------------
local function assert_cap(obj, field, label)
  if not obj or type(obj[field]) == "nil" then
    logging.warn("[memoscape] MISSING CAPABILITY: " .. label ..
      " — feature disabled. Check Halo SDK version.")
    return false
  end
  return true
end

local HAS_BLUETOOTH  = assert_cap(halo, "bluetooth",  "halo.bluetooth")
local HAS_DISPLAY    = assert_cap(halo, "display",    "halo.display")
local HAS_CAMERA     = assert_cap(halo, "camera",     "halo.camera")
local HAS_MICROPHONE = assert_cap(halo, "microphone", "halo.microphone")
local HAS_POWER      = assert_cap(halo, "power",      "halo.power")
local HAS_FILE       = assert_cap(halo, "file",       "halo.file")
local HAS_TICK       = assert_cap(halo, "on_tick",    "halo.on_tick")

-- ---------------------------------------------------------------------------
-- BLE receive opcode → state machine event mapping
-- All physical events (button, IMU, host messages) arrive here in tick().
-- Envelope format from host: { "t": "<type>", ... }
-- ---------------------------------------------------------------------------
local BUTTON_OPCODE_MAP = {
  single = E.EVENTS.single_click,
  double = E.EVENTS.double_click,
  long   = E.EVENTS.long_press,
}

local function process_inbound(raw)
  if not raw or raw == "" then return end
  -- host_comm handles framing / reassembly; returns parsed table or nil
  local msg = host_comm.on_receive(raw)
  if not msg then return end

  local t = msg.t
  if t == "button" then
    local ev = BUTTON_OPCODE_MAP[msg.ev]
    if ev then
      state_machine.dispatch(ev)
    else
      logging.warn("[memoscape] unknown button opcode: " .. tostring(msg.ev))
    end

  elseif t == "imu_tap" then
    state_machine.dispatch(E.EVENTS.imu_tap)

  elseif t == "connect" then
    session.start(time.now())
    state_machine.dispatch(E.EVENTS.host_connected)

  elseif t == "disconnect" then
    session.end_session()
    state_machine.dispatch(E.EVENTS.host_disconnected)

  else
    -- All other message types (card payloads, commands) handled by host_comm
    host_comm.on_message(msg)
  end
end

-- ---------------------------------------------------------------------------
-- Boot
-- ---------------------------------------------------------------------------
local function boot()
  time.bind(halo.time and halo.time.now or function() return 0 end)
  logging.bind and logging.info("Memoscape boot")

  if HAS_FILE    then settings.bind(halo.file);       settings.load() end
  if HAS_POWER   then power.bind(halo.power)                          end
  if HAS_CAMERA  then camera.bind(halo.camera)                        end
  if HAS_MICROPHONE then microphone.bind(halo.microphone)             end
  scheduler.bind(camera, microphone, activity)
  if HAS_BLUETOOTH then host_comm.bind(halo.bluetooth) end
  if HAS_DISPLAY   then renderer.bind(halo.display, time.now) end
  anim.enabled = not settings.get("reduce_motion")

  state_machine.init(renderer, scheduler, function(old, new, ev)
    logging.info("state " .. old .. " -> " .. new .. " (" .. tostring(ev) .. ")")
  end)

  state_machine.dispatch(E.EVENTS.startup)
end

-- ---------------------------------------------------------------------------
-- Cooperative event loop tick
-- This is the ONLY place inbound BLE data is consumed on device.
-- halo.bluetooth.receive() returns the next pending raw string or nil.
-- ---------------------------------------------------------------------------
local function tick()
  -- 1. Drain BLE receive buffer
  if HAS_BLUETOOTH and halo.bluetooth.receive then
    local raw = halo.bluetooth.receive()
    while raw do
      process_inbound(raw)
      raw = halo.bluetooth.receive()
    end
  end

  -- 2. Advance renderer animations
  renderer.tick()

  -- 3. Poll power events (low-battery, etc.)
  if HAS_POWER then
    local pe = power.poll()
    if pe then state_machine.dispatch(pe) end
  end
end

boot()
if HAS_TICK then halo.on_tick(tick) end
_G.memoscape = { tick = tick, state = state_machine.state }
return _G.memoscape
