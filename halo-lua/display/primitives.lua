--- display/primitives.lua
--- Thin wrappers around the real Brilliant Labs frame.display.* API.
---
--- FIXED: previous version used frame.display.bitmap() which does NOT
--- exist in the real emulator, and passed {r,g,b} 0-1 tables as color
--- arguments.  All calls now use the verified frame.display API and
--- 0xRRGGBB integer colors.
---
--- HAS_FRAME guard: every function no-ops silently when frame is absent
--- so Python CI / offline pytest never crashes on require.

local math       = math
local HAS_FRAME  = (type(_G.frame) == "table")

local T = require("display.typography")

local primitives = {}

-- ---------------------------------------------------------------------------
-- Meridian Solid: live font sizes. Cached so repeated same-size text costs
-- nothing; pcall-latched so a firmware without (or with a different)
-- set_font degrades the WHOLE feature to today's single-size text by
-- flipping nothing but _font_wired — no other code path changes.
-- ---------------------------------------------------------------------------
local _font_wired = true
local _cur_size   = nil

function primitives.set_font_size(size)
  if not HAS_FRAME or not _font_wired then return end
  size = T.DEVICE_FONT[size] and size or T.DEFAULT_SIZE
  if size == _cur_size then return end
  local f = T.DEVICE_FONT[size]
  local ok = pcall(frame.display.set_font, f.fid, f.sz, f.sc)
  if not ok then
    _font_wired = false   -- device seam absent: single-size text forever
    return
  end
  _cur_size = size
end

function primitives.font_wired()
  return _font_wired
end

function primitives._reset_font_for_test()
  _font_wired, _cur_size = true, nil
end

--- Draw a filled circle (dot).
--- @param x      number  centre x
--- @param y      number  centre y
--- @param r      number  radius in px
--- @param color  number  0xRRGGBB integer
function primitives.dot(x, y, r, color)
  if not HAS_FRAME then return end
  frame.display.circle(math.floor(x), math.floor(y),
                       math.max(1, math.floor(r)), color, true)
end

--- Draw an outlined circle (ring).
--- @param cx     number
--- @param cy     number
--- @param r      number  radius
--- @param _stroke number  ignored (frame API has no stroke width; kept for API compat)
--- @param color  number  0xRRGGBB integer
function primitives.circle(cx, cy, r, _stroke, color)
  if not HAS_FRAME then return end
  frame.display.circle(math.floor(cx), math.floor(cy),
                       math.max(1, math.floor(r)), color, false)
end

--- Draw a horizontal line.
--- @param x1    number
--- @param x2    number
--- @param y     number
--- @param color number  0xRRGGBB integer
function primitives.hline(x1, x2, y, color)
  if not HAS_FRAME then return end
  frame.display.line(math.floor(x1), math.floor(y),
                     math.floor(x2), math.floor(y), color)
end

--- Draw a vertical bar (filled rect).
--- @param x   number  left edge
--- @param y1  number  top
--- @param y2  number  bottom
--- @param w   number  width in px
--- @param color number  0xRRGGBB integer
function primitives.vbar(x, y1, y2, w, color)
  if not HAS_FRAME then return end
  local h = math.abs(math.floor(y2) - math.floor(y1))
  if h < 1 then h = 1 end
  frame.display.rect(math.floor(x), math.floor(y1),
                     math.max(1, math.floor(w)), h, color, true)
end

--- Draw a text string at (x, y) in a size token (Solid: the size stub is
--- live). Unsized calls resolve to DEFAULT_SIZE explicitly, so a large
--- font can never leak ("stick") into a module that didn't ask for one.
--- @param x     number
--- @param y     number
--- @param text  string
--- @param size  string|nil  typography size token ("hero".."sm")
--- @param color number  0xRRGGBB integer
function primitives.text_center(x, y, text, size, color)
  if not HAS_FRAME then return end
  primitives.set_font_size(size or T.DEFAULT_SIZE)
  -- frame.display.text(txt, x, y, color_int) -- no table argument
  frame.display.text(tostring(text), math.floor(x), math.floor(y), color)
end

return primitives
