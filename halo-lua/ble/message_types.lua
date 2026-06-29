-- ble/message_types.lua
-- Message type constants.
-- These are the string values carried in the `t` field of every
-- JSON envelope exchanged between real_bridge.py and the Halo Lua runtime.
--
-- Inbound (host -> Halo):
--   card     : display a HUD card  (payload in msg.payload)
--   command  : low-level command   (kind in msg.kind)
--
-- Originated on-device, echoed by host for dispatch:
--   button       : physical button event (ev: "single" | "double" | "long")
--   imu_tap      : IMU double-tap gesture
--   connect      : BLE session established
--   disconnect   : BLE session dropped
--
-- Misc / error:
--   parse_error  : host signals a decode failure
--   event        : generic named event from host (name in msg.name)

local MT = {
  -- Inbound from host
  CARD            = "card",
  COMMAND         = "command",

  -- Physical events (arrive as JSON envelopes via BLE receive)
  BUTTON          = "button",
  IMU_TAP         = "imu_tap",
  CONNECT         = "connect",
  DISCONNECT      = "disconnect",

  -- Misc
  PARSE_ERROR     = "parse_error",
  EVENT           = "event",

  -- Button event values (msg.ev)
  BTN_SINGLE      = "single",
  BTN_DOUBLE      = "double",
  BTN_LONG        = "long",

  -- Command kind values (msg.kind) sent by host
  CMD_SHOW_READY  = "show_ready",
  CMD_PAUSE       = "pause",
  CMD_RESUME      = "resume",
  CMD_ASK         = "ask",
  CMD_WAKE        = "wake",
  CMD_RESET       = "reset",
}

return MT
