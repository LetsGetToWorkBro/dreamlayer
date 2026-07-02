--- display/palette.lua
--- Semantic color tokens + Halo Cinema v1 dynamic palette slot bank.
---
--- Static tokens (never reassigned at runtime) mirror
--- host-python/src/dreamlayer/hud/themes.py — keep the two in sync.
---
--- Dynamic bank (Halo Cinema v1, docs/HALO_CINEMA_V1.md §1.2):
--- the 4bpp display has no alpha; "opacity" is faked by animating the
--- YCbCr of a reserved palette slot via frame.display.assign_color_ycbcr.
--- Slots 1-6 form the dynamic bank; slot 0 (background) and slots 7-15
--- (static semantic colors) are never reassigned.
---
--- Public API:
---   M.reserve_dynamic(name, base_hex [, slot]) -> slot index (idempotent)
---   M.dynamic_slot(name)   -> slot index or nil
---   M.dynamic_color(name)  -> base 0xRRGGBB for draw calls
---   M.shift_dynamic(name, dy, dcb, dcr)  -> animate slot off its base
---   M.set_dynamic_y(name, y)             -> luma-only ramp (ghost fades)
---   M.restore(name) / M.restore_all()    -> snap back to base color

local M = {}

M.background        = 0x000000
M.surface           = 0x0E1416

M.text_primary      = 0xECF0F1
M.text_secondary    = 0xA8B8C0
M.text_ghost        = 0x58686F

M.accent_memory     = 0x2CC79A
M.accent_memory_dim = 0x1A7A60
M.memory_rail       = 0x2CC79A

M.accent_attention  = 0xE06B52
M.accent_success    = 0x56D364
M.accent_error      = 0xE05252

M.border_subtle     = 0x2A3C44
M.status_paused     = 0x8FA8B2

-- AAA visual pass additions
M.memory_trace      = 0x00FFAA
M.confidence_low    = 0xFFAA00
M.confidence_med    = 0x00FFAA
M.confidence_high   = 0xB8FFE9  -- Meridian: v1's 0xAA00FF violet read
                                -- off-family next to the teal system
                                -- (flagged in HALO_CINEMA_V1_RISKS.md and
                                -- CINEMA_V1_JUDGMENT.md); highest
                                -- confidence is now the brightest member
                                -- of the family, not a foreign hue
M.privacy_danger    = 0xFF4444
M.privacy_caution   = 0xFF8800
M.warning_amber     = 0xFF6600

-- ---------------------------------------------------------------------------
-- Dynamic slot bank
-- ---------------------------------------------------------------------------

local DYNAMIC_MIN, DYNAMIC_MAX = 1, 6

local HAS_FRAME = (type(_G.frame) == "table")

-- name -> { slot = n, base = 0xRRGGBB }
local _reserved  = {}
local _next_slot = DYNAMIC_MIN

--- Convert 0xRRGGBB to the 0-1023 YCbCr triple used by assign_color_ycbcr.
--- BT.601 full-range, scaled 0-255 -> 0-1023 (x4).
function M.hex_to_ycbcr(hex)
  local r = (hex >> 16) & 0xFF
  local g = (hex >> 8)  & 0xFF
  local b =  hex        & 0xFF
  local y  =  0.299 * r + 0.587 * g + 0.114 * b
  local cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
  local cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
  local function q(v) return math.max(0, math.min(1023, math.floor(v * 4 + 0.5))) end
  return q(y), q(cb), q(cr)
end

--- Reserve a dynamic palette slot for `name`, backed by base color base_hex.
--- Idempotent: reserving the same name again returns the same slot.
--- Pass an explicit `slot` to alias a mode-exclusive slot (e.g. the dream
--- drift slots double as prism fringe slots in card mode).
--- @return number  slot index in [1, 6]
function M.reserve_dynamic(name, base_hex, slot)
  local existing = _reserved[name]
  if existing then return existing.slot end
  if slot == nil then
    slot = _next_slot
    _next_slot = _next_slot + 1
  end
  assert(slot >= DYNAMIC_MIN and slot <= DYNAMIC_MAX,
         "dynamic palette bank exhausted (slots " .. DYNAMIC_MIN .. "-" .. DYNAMIC_MAX .. ")")
  _reserved[name] = { slot = slot, base = base_hex or M.text_ghost }
  M.restore(name)
  return slot
end

function M.dynamic_slot(name)
  local r = _reserved[name]
  return r and r.slot or nil
end

function M.dynamic_color(name)
  local r = _reserved[name]
  return r and r.base or M.text_ghost
end

--- Reassign a reserved slot, offset from its base color.
--- dy/dcb/dcr are added to the base YCbCr (0-1023 scale), clamped.
function M.shift_dynamic(name, dy, dcb, dcr)
  local r = _reserved[name]
  if not r then return end
  if not HAS_FRAME then return end
  local y, cb, cr = M.hex_to_ycbcr(r.base)
  local function c(v) return math.max(0, math.min(1023, math.floor(v + 0.5))) end
  frame.display.assign_color_ycbcr(r.slot, c(y + (dy or 0)), c(cb + (dcb or 0)), c(cr + (dcr or 0)))
end

--- Set a reserved slot's luma directly (0-1023), keeping base chroma.
function M.set_dynamic_y(name, y)
  local r = _reserved[name]
  if not r then return end
  if not HAS_FRAME then return end
  local _, cb, cr = M.hex_to_ycbcr(r.base)
  frame.display.assign_color_ycbcr(r.slot, math.max(0, math.min(1023, math.floor(y + 0.5))), cb, cr)
end

--- Snap a reserved slot back to its base color.
function M.restore(name)
  local r = _reserved[name]
  if not r then return end
  if not HAS_FRAME then return end
  local y, cb, cr = M.hex_to_ycbcr(r.base)
  frame.display.assign_color_ycbcr(r.slot, y, cb, cr)
end

function M.restore_all()
  for name in pairs(_reserved) do M.restore(name) end
end

--- Test/emulator hook: reserved names, sorted for determinism.
function M.reserved_names()
  local names = {}
  for name in pairs(_reserved) do names[#names + 1] = name end
  table.sort(names)
  return names
end

return M
