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

return layout
