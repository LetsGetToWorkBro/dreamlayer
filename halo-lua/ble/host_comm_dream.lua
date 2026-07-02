--- ble/host_comm_dream.lua
--- Dream Mode extensions to the host_comm BLE message handler.
---
--- Adds handlers for:
---   t = "palette"      palette shift from MicReactor
---   t = "geometry"     distortion from ImuReactor
---   t = "sprite"       bitmap frame from SpriteBridge
---   t = "dream_enter"  enter Dream Mode
---   t = "dream_exit"   exit Dream Mode
---
--- Wire into the main host_comm dispatch table:
---   local DC = require("ble/host_comm_dream")
---   DC.register(dispatch_table)

local DR = require("display/dream_renderer")

local M = {}

-- Dream mode active flag (mirrored from host state)
local _dream_active = false

-- ---------------------------------------------------------------------------
-- Registration helper
-- ---------------------------------------------------------------------------

function M.register(dispatch)
  dispatch["palette"]     = M.on_palette
  dispatch["geometry"]    = M.on_geometry
  dispatch["line_field"]  = M.on_line_field
  dispatch["sprite"]      = M.on_sprite
  dispatch["sprite_avatar"] = M.on_sprite   -- same decode path; x/y placement
  dispatch["dream_enter"] = M.on_dream_enter
  dispatch["dream_exit"]  = M.on_dream_exit
end

-- ---------------------------------------------------------------------------
-- Handlers
-- ---------------------------------------------------------------------------

function M.on_palette(msg)
  -- msg: {t="palette", colors=[{idx,y,cb,cr},...], duration_ms=int}
  local colors = msg.colors
  if type(colors) ~= "table" then return end
  DR.apply_palette_shift(colors)
end

function M.on_geometry(msg)
  -- msg: {t="geometry", mode="rotate"|"scatter", intensity=float,
  --       yaw_rate=float, pitch_rate=float}
  DR.on_geometry(msg)
end

function M.on_line_field(msg)
  -- msg: {t="line_field", v=[x1,y1,x2,y2, ...12 vectors]}
  -- Line Field 2.0: curl-noise vectors computed host-side (imu_reactor.py),
  -- one MTU frame per tick.
  DR.on_line_field(msg)
end

function M.on_sprite(msg)
  -- msg: {t="sprite", data=binary_packed_sprite, x=int?, y=int?}
  -- The brilliant-msg layer has already reassembled the chunked BLE frames.
  -- msg.data is the raw packed TxSprite payload. Optional x/y anchor the
  -- sprite (SynesthesiaCard v2 sends y=128 for its bottom-half sprite;
  -- Social Lens avatars send their 32×32 placement).
  if not msg.data then return end
  local HAS_FRAME = (type(_G.frame) == "table")
  if not HAS_FRAME then return end
  -- Decode sprite: brilliant-msg sprite.lua handles this
  local ok, spr = pcall(function()
    local sprite_lib = require("sprite")   -- brilliant-msg sprite module
    return sprite_lib.decode(msg.data)
  end)
  if not ok or not spr then return end
  frame.display.bitmap(
    msg.x or 1, msg.y or 1,
    spr.width,
    2 ^ spr.bpp,
    0,
    spr.pixel_data,
    { palette_data = spr.palette_data }
  )
end

function M.on_dream_enter(_msg)
  _dream_active = true
  -- Clear display, let dream renderer take over
  local HAS_FRAME = (type(_G.frame) == "table")
  if HAS_FRAME then
    frame.display.clear()
  end
end

function M.on_dream_exit(_msg)
  _dream_active = false
  local HAS_FRAME = (type(_G.frame) == "table")
  if HAS_FRAME then
    frame.display.clear()
  end
end

function M.is_active()
  return _dream_active
end

return M
