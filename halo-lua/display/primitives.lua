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

local primitives = {}

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

--- Draw a text string at (x, y).
--- @param x     number
--- @param y     number
--- @param text  string
--- @param _size number  font-size token -- passed to set_font if you wire it; otherwise ignored
--- @param color number  0xRRGGBB integer
function primitives.text_center(x, y, text, _size, color)
  if not HAS_FRAME then return end
  -- frame.display.text(txt, x, y, color_int) -- no table argument
  frame.display.text(tostring(text), math.floor(x), math.floor(y), color)
end

return primitives
