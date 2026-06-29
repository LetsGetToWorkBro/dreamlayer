--- display/primitives.lua
--- Thin wrappers around frame.display.* draw calls.
---
--- These normalise the calling convention so cards.lua and animations.lua
--- never call frame.display directly — all drawing goes through here.
--- This makes mocking trivial in the emulator and unit tests.

local primitives = {}

--- Draw a filled circle (dot).
--- @param x  number  centre x
--- @param y  number  centre y
--- @param r  number  radius in px
--- @param color table  {r,g,b} normalised 0-1
function primitives.dot(x, y, r, color)
    frame.display.bitmap("dot", x - r, y - r, 2 * r, 2 * r,
        color[1], color[2], color[3])
end

--- Draw an outlined circle (ring).
--- @param cx     number
--- @param cy     number
--- @param r      number
--- @param stroke number  line width in px
--- @param color  table   {r,g,b} normalised 0-1
function primitives.circle(cx, cy, r, stroke, color)
    for i = 0, 359 do
        local rad = math.rad(i)
        local x = cx + r * math.cos(rad)
        local y = cy + r * math.sin(rad)
        primitives.dot(x, y, stroke / 2, color)
    end
end

--- Draw a horizontal line.
--- @param x1    number
--- @param x2    number
--- @param y     number
--- @param color table  {r,g,b}
function primitives.hline(x1, x2, y, color)
    frame.display.bitmap("hline", x1, y, x2 - x1, 1,
        color[1], color[2], color[3])
end

--- Draw a vertical rectangle (bar).
--- @param x  number  left edge
--- @param y1 number  top
--- @param y2 number  bottom
--- @param w  number  width in px
--- @param color table  {r,g,b}
function primitives.vbar(x, y1, y2, w, color)
    frame.display.bitmap("vbar", x, y1, w, y2 - y1,
        color[1], color[2], color[3])
end

--- Draw a text string centred at (x, y).
--- @param x      number
--- @param y      number
--- @param text   string
--- @param size   number  font size token (use typography constants)
--- @param color  table   {r,g,b}
function primitives.text_center(x, y, text, size, color)
    frame.display.text(text, x, y,
        { color = color, size = size, align = "center" })
end

return primitives
