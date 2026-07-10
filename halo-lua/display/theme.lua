--- display/theme.lua — Forkable Skin (INNOVATION_SESSION 3.6).
---
--- The in-eye design language is data: a theme is a Lua table that restyles the
--- semantic palette, the five-step type scale, and motion durations, loaded at
--- boot and applied over display/palette.lua + display/typography.lua. A
--- cyberpunk skin, an accessibility ultra-high-contrast skin, a paper-and-ink
--- skin are all just tables — no fork of the renderer.
---
--- The budget the validator enforces (so a skin can never break what's provable
--- about a frame):
---   * a theme may restyle only the STATIC identity — the named semantic color
---     tokens. The dynamic slot bank (slots 1-6) is leased at runtime by
---     dream/prism/confluence; it is off the allowlist, so a theme literally
---     cannot name it, and the "≤8 palette writes / tick" invariant is
---     untouched.
---   * type sizes must stay in the physical font band [10,22]px, so restyled
---     text still fits the 112px safe radius and the line budget.
---   * motion durations are bounded, so a skin can't set a 0ms strobe or a
---     10s freeze that breaks the 50ms tick loop.
--- A theme that fails validation is refused whole — no partial skin.

local palette = require("display.palette")
local typography = require("display.typography")

local M = {}

-- the semantic color tokens a theme may restyle (the static identity only)
M.COLOR_KEYS = {
  "background", "surface",
  "text_primary", "text_secondary", "text_ghost",
  "accent_memory", "accent_attention", "accent_success", "accent_error",
  "border_subtle", "warning_amber", "privacy_danger", "privacy_caution",
}
-- the five type-scale steps
M.SIZE_KEYS = { "hero", "xl", "lg", "md", "sm" }

M.FONT_MIN, M.FONT_MAX = 10, 22
M.MOTION_MIN_MS, M.MOTION_MAX_MS = 50, 4000

M.active = nil        -- name of the applied theme (nil = shipped defaults)
M.motion = {}         -- applied motion overrides

local function is_hex(v)
  return type(v) == "number" and v >= 0 and v <= 0xFFFFFF and math.floor(v) == v
end

local function keyset(list)
  local s = {}
  for _, k in ipairs(list) do s[k] = true end
  return s
end

--- Validate a theme table against the skin budget.
--- @return boolean ok, table issues  (issues empty when ok)
function M.validate(theme)
  local issues = {}
  if type(theme) ~= "table" then return false, { "theme must be a table" } end
  if type(theme.name) ~= "string" or theme.name == "" then
    issues[#issues + 1] = "theme.name must be a non-empty string"
  end

  local color_ok = keyset(M.COLOR_KEYS)
  for k, v in pairs(theme.colors or {}) do
    if not color_ok[k] then
      issues[#issues + 1] = "unknown color token '" .. tostring(k) ..
        "' — a theme may restyle the static identity, never the dynamic bank"
    elseif not is_hex(v) then
      issues[#issues + 1] = "color '" .. tostring(k) .. "' must be 0x000000..0xFFFFFF"
    end
  end

  local size_ok = keyset(M.SIZE_KEYS)
  for k, spec in pairs(theme.typography or {}) do
    if not size_ok[k] then
      issues[#issues + 1] = "unknown type step '" .. tostring(k) .. "'"
    elseif type(spec) ~= "table" or type(spec.sz) ~= "number" then
      issues[#issues + 1] = "type step '" .. tostring(k) .. "' needs { sz = <px> }"
    elseif spec.sz < M.FONT_MIN or spec.sz > M.FONT_MAX then
      issues[#issues + 1] = "type step '" .. tostring(k) .. "' sz " .. spec.sz ..
        " is outside the [" .. M.FONT_MIN .. "," .. M.FONT_MAX .. "] font band"
    end
  end

  for k, ms in pairs(theme.motion or {}) do
    if type(ms) ~= "number" or ms < M.MOTION_MIN_MS or ms > M.MOTION_MAX_MS then
      issues[#issues + 1] = "motion '" .. tostring(k) .. "' must be [" ..
        M.MOTION_MIN_MS .. "," .. M.MOTION_MAX_MS .. "] ms"
    end
  end

  return #issues == 0, issues
end

--- Apply a validated theme onto the live palette + typography tables.
--- Refused whole if it fails validation (no partial skin).
--- @return boolean ok, table issues
function M.apply(theme)
  local ok, issues = M.validate(theme)
  if not ok then return false, issues end
  for k, v in pairs(theme.colors or {}) do
    palette[k] = v
  end
  for k, spec in pairs(theme.typography or {}) do
    local cur = typography.DEVICE_FONT[k]
    if cur then
      cur.sz = spec.sz
      if spec.sc then cur.sc = spec.sc end
      if spec.fid then cur.fid = spec.fid end
    end
  end
  M.motion = theme.motion or {}
  M.active = theme.name
  return true, {}
end

--- A themed motion duration, or `default` when the active theme doesn't set it.
function M.motion_ms(key, default)
  return M.motion[key] or default
end

return M
