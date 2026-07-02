--- display/layout.lua
--- Shared layout constants and helper functions for the 256x256 display.
---
--- All pixel values are absolute, origin top-left.
--- Coordinate system matches frame.display and cards.lua.

local layout = {}

--- Display dimensions
layout.W      = 256
layout.H      = 256
layout.CX     = 128   -- horizontal centre
layout.CY     = 128   -- vertical centre
layout.RADIUS = 128   -- circular clip radius

--- Safe area (stays inside the circular clip with a comfortable margin)
layout.SAFE_L = 22
layout.SAFE_R = 234
layout.SAFE_T = 32
layout.SAFE_B = 224

--- Typography row y-positions used by multiple card types.
--- Kept here so cards.lua and renderer.lua stay in sync.
layout.ROW_EYEBROW   = 76
layout.ROW_SEPARATOR = 92
layout.ROW_PRIMARY   = 116
layout.ROW_DETAIL    = 148
layout.ROW_FOOTER    = 173
layout.ROW_CONF_DOT  = 196

--- Separator line x extents
layout.SEP_X1 = 54
layout.SEP_X2 = 202

--- Left accent bar
layout.VBAR_X  = 22
layout.VBAR_Y1 = 104
layout.VBAR_Y2 = 128
layout.VBAR_W  = 2

--- Clamp a value to [lo, hi].
--- @param v  number
--- @param lo number
--- @param hi number
--- @return   number
function layout.clamp(v, lo, hi)
    return math.max(lo, math.min(hi, v))
end

--- Return true if point (x, y) is inside the circular safe area.
--- @param x number
--- @param y number
--- @return   boolean
function layout.in_circle(x, y)
    local dx = x - layout.CX
    local dy = y - layout.CY
    return (dx * dx + dy * dy) <= (layout.RADIUS * layout.RADIUS)
end

--- Safe-area inset radius (16px inside the circular clip).
layout.SAFE_INSET_RADIUS = layout.RADIUS - 16

--- Debug-build guard: assert that a circle of radius r centred at (x, y)
--- stays inside the circular safe area. Only raises when debug builds set
--- layout.DEBUG = true (draw calls must never crash production).
--- @param x number  centre x
--- @param y number  centre y
--- @param r number  radius of the drawn element (0 for points/text anchors)
--- @return  boolean true if inside the safe area
function layout.assert_safe(x, y, r)
    r = r or 0
    local dx = x - layout.CX
    local dy = y - layout.CY
    local ok = (math.sqrt(dx * dx + dy * dy) + r) <= layout.SAFE_INSET_RADIUS
    if layout.DEBUG and not ok then
        error(string.format(
            "layout.assert_safe: element at (%d,%d) r=%d escapes safe radius %d",
            math.floor(x), math.floor(y), math.floor(r), layout.SAFE_INSET_RADIUS))
    end
    return ok
end

return layout
