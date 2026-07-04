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

  -- Dream Mode / Halo Cinema v1 raw frames (host -> Halo)
  PALETTE         = "palette",        -- palette weather {colors=[{idx,y,cb,cr}]}
  GEOMETRY        = "geometry",       -- legacy particle/line distortion
  LINE_FIELD      = "line_field",     -- Line Field 2.0 {v=[48 ints]}
  SPRITE          = "sprite",         -- TxSprite bitmap {data, x?, y?}
  SPRITE_AVATAR   = "sprite_avatar",  -- 32x32 contact avatar (contacts ONLY)
  DREAM_ENTER     = "dream_enter",
  DREAM_EXIT      = "dream_exit",

  -- Meridian (Cinema v2): the composed day-ring
  -- {t="horizon", seq=n, paused=0|1, v=[dd,code, dd,code, …]} — ≤48 marks,
  -- dd = deci-degrees screen space, code = kind*100+state*10+luma
  -- (docs/cinema_v2/horizon_frame.md; Python side orchestrator/
  -- horizon_composer.py — keep in sync)
  HORIZON         = "horizon",

  -- Yesterlight: in-place time scrub (host -> Halo)
  -- {t="yesterlight", active=0|1, notch_dd=deci-deg, echo_dd=deci-deg?}
  -- Python side dream_mode/yesterlight.py MSG_YESTERLIGHT — keep in sync
  YESTERLIGHT     = "yesterlight",

  -- Timbre: known-voice waveform at the rim (host -> Halo)
  -- {t="timbre", known=0|1, side_dd=deci-deg, points=[12 ints 1..15]}
  -- Python side dream_mode/timbre_reactor.py MSG_TIMBRE — keep in sync
  TIMBRE          = "timbre",

  -- Confluence: two wearers, one entangled sky (host -> Halo)
  -- {t="confluence", mode="merged"|"split"|"solo", tg=0..100,
  --  seam_dd=deci-deg?, gap_deg=?, peer_rgb={r,g,b}?}
  -- Python side confluence/entangle.py MSG_CONFLUENCE — keep in sync
  CONFLUENCE      = "confluence",

  -- TinCan: silent gesture ping from the bonded peer (host -> Halo)
  -- {t="tincan", side_dd=deci-deg, pulses=[ms,…], gap_ms=n}
  -- Python side confluence/tincan.py MSG_TINCAN — keep in sync
  TINCAN          = "tincan",

  -- Prism Lens: the psychedelic kaleidoscope overlay (host -> Halo)
  -- {t="prism", active=0|1, intensity=0..100, symmetry=n, hue_rate=n}
  -- Python side dream_mode/prism.py MSG_PRISM — keep in sync
  PRISM           = "prism",

  -- Live voice level while QueryListeningCard holds (host -> Halo)
  -- {t="amp", v=0..99} — ~15 bytes, sent only during capture; the
  -- waveform tracks the wearer's actual voice (Lumen). Python side
  -- hud/cards.py amp_message — keep in sync
  AMP             = "amp",

  -- Physical events (arrive as JSON envelopes via BLE receive)
  BUTTON          = "button",
  IMU_TAP         = "imu_tap",
  CONNECT         = "connect",
  DISCONNECT      = "disconnect",

  -- Misc
  PARSE_ERROR     = "parse_error",
  EVENT           = "event",

  -- Reality Compiler v2 figments (host <-> app/figment_stage.lua;
  -- Python side mirrored in reality_compiler/v2/transport.py — keep in sync)
  FIGMENT_PUT     = "figment_put",     -- host -> Halo: store figment (inactive)
  FIGMENT_SWAP    = "figment_swap",    -- host -> Halo: hot-swap between ticks
  FIGMENT_REVOKE  = "figment_revoke",  -- host -> Halo: stop + clear, go ambient
  FIGMENT_TEXT    = "figment_text",    -- host -> Halo: push into the text slot
  FIGMENT_ACK     = "figment_ack",     -- Halo -> host: put/swap/revoke result
  FIGMENT_EVENT   = "figment_event",   -- Halo -> host: rate-limited emit

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
