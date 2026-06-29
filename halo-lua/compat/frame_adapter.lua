--- compat/frame_adapter.lua
--- Compatibility shim: builds _G.halo from the real Brilliant Labs
--- frame.* global.  Also exposes all new drawing primitives as
--- halo.display.bezier, halo.display.elliptical_arc, etc.
---
--- Usage (top of main.lua):
---   require("compat.frame_adapter")
---   local halo = _G.halo
---
--- Falls back to a no-op mock when frame is absent (keeps Python
--- host tests and offline CI passing).
---
--- FIXED over 99ece13:
---   - radial_rays signature unified with renderer.lua:
---     (cx, cy, r_min, r_max, n_rays, color, bloom_r)

local math = math

-- ---------------------------------------------------------------------------
-- Detect runtime environment
-- ---------------------------------------------------------------------------
local HAS_FRAME = (type(_G.frame) == "table")

-- ---------------------------------------------------------------------------
-- No-op mock used when frame is absent
-- ---------------------------------------------------------------------------
local function noop(...) end
local function noop_bool() return false end

local mock_display = setmetatable({}, {
  __index = function(_, k)
    return function(...)
      -- silent no-op; useful in CI / Python test context
    end
  end
})

local mock_bt = {
  send             = noop,
  receive_callback = noop,
  receive          = function() return nil end,
}

local mock_button = {
  single = noop, double = noop, long = noop,
}

local mock_imu = { tap_callback = noop }

-- ---------------------------------------------------------------------------
-- Primitive approximations  (all marked APPROX per spec)
-- ---------------------------------------------------------------------------

--- APPROX: quadratic_bezier
--- Renders as polyline of `steps` line segments via parametric t=0..1
local function bezier(p0, p1, p2, color, steps)
  if not HAS_FRAME then return end
  steps = steps or 24
  local prev_x = p0[1] or p0.x
  local prev_y = p0[2] or p0.y
  for i = 1, steps do
    local t  = i / steps
    local mt = 1 - t
    local x  = mt*mt*(p0[1] or p0.x) + 2*mt*t*(p1[1] or p1.x) + t*t*(p2[1] or p2.x)
    local y  = mt*mt*(p0[2] or p0.y) + 2*mt*t*(p1[2] or p1.y) + t*t*(p2[2] or p2.y)
    frame.display.line(math.floor(prev_x), math.floor(prev_y),
                       math.floor(x),      math.floor(y), color)
    prev_x, prev_y = x, y
  end
end

--- APPROX: elliptical_arc
--- Renders as polyline via math.cos/sin; steps = arc resolution
local function elliptical_arc(cx, cy, rx, ry, start_deg, end_deg, color, steps)
  if not HAS_FRAME then return end
  steps = steps or 32
  local function pt(deg)
    local r = math.rad(deg)
    return cx + rx * math.cos(r), cy + ry * math.sin(r)
  end
  local sweep = end_deg - start_deg
  local x0, y0 = pt(start_deg)
  for i = 1, steps do
    local deg = start_deg + sweep * i / steps
    local x1, y1 = pt(deg)
    frame.display.line(math.floor(x0), math.floor(y0),
                       math.floor(x1), math.floor(y1), color)
    x0, y0 = x1, y1
  end
end

--- APPROX: polyline
--- Loop of frame.display.line(points[i] -> points[i+1])
local function polyline(points, color)
  if not HAS_FRAME then return end
  for i = 1, #points - 1 do
    local a, b = points[i], points[i+1]
    frame.display.line(math.floor(a[1] or a.x), math.floor(a[2] or a.y),
                       math.floor(b[1] or b.x), math.floor(b[2] or b.y), color)
  end
end

--- APPROX: polar_segments
--- Compute segment endpoints via math.cos/sin; lit segs drawn bright,
--- ghost segs drawn with ghost_color
local function polar_segments(cx, cy, r_inner, r_outer, n_segs, lit_segs, color, ghost_color)
  if not HAS_FRAME then return end
  ghost_color = ghost_color or color
  local lit_set = {}
  for _, v in ipairs(lit_segs) do lit_set[v] = true end
  local step = (2 * math.pi) / n_segs
  for i = 0, n_segs - 1 do
    local angle = step * i - math.pi / 2
    local xi = cx + r_inner * math.cos(angle)
    local yi = cy + r_inner * math.sin(angle)
    local xo = cx + r_outer * math.cos(angle)
    local yo = cy + r_outer * math.sin(angle)
    local c  = lit_set[i] and color or ghost_color
    frame.display.line(math.floor(xi), math.floor(yi),
                       math.floor(xo), math.floor(yo), c)
  end
end

--- APPROX: radial_rays
--- frame.display.line per ray + frame.display.circle at tip for bloom dot
--- FIXED: signature is now (cx, cy, r_min, r_max, n_rays, color, bloom_r)
--- to match renderer.lua local radial_rays -- both must be identical.
local function radial_rays(cx, cy, r_min, r_max, n_rays, color, bloom_r)
  if not HAS_FRAME then return end
  bloom_r = bloom_r or 2
  local step = (2 * math.pi) / n_rays
  for i = 0, n_rays - 1 do
    local angle = step * i - math.pi / 2
    local x1 = cx + r_min * math.cos(angle)
    local y1 = cy + r_min * math.sin(angle)
    local x2 = cx + r_max * math.cos(angle)
    local y2 = cy + r_max * math.sin(angle)
    frame.display.line(math.floor(x1), math.floor(y1),
                       math.floor(x2), math.floor(y2), color)
    -- bloom dot at tip
    frame.display.circle(math.floor(x2), math.floor(y2), bloom_r, color, false)
  end
end

--- APPROX: check_glyph
--- Two frame.display.line calls forming a checkmark polyline
local function check_glyph(cx, cy, size, color)
  if not HAS_FRAME then return end
  local s = size / 60.0
  local ax, ay   = cx - math.floor(21*s), cy
  local bx, by   = cx - math.floor(3*s),  cy + math.floor(18*s)
  local ccx, ccy = cx + math.floor(21*s), cy - math.floor(22*s)
  frame.display.line(ax, ay, bx, by, color)
  frame.display.line(bx, by, ccx, ccy, color)
end

--- APPROX: shield_glyph
--- frame.display.polygon with 6 points approximating hexagon outline,
--- plus two rect pause bars inside
local function shield_glyph(cx, cy, size, color, pause_bars)
  if not HAS_FRAME then return end
  if pause_bars == nil then pause_bars = true end
  local hw = size / 2
  local pts = {}
  for i = 0, 5 do
    local angle = math.rad(60 * i - 30)
    pts[#pts+1] = { math.floor(cx + hw * math.cos(angle)),
                    math.floor(cy + hw * math.sin(angle)) }
  end
  -- Draw as polyline (close manually)
  pts[#pts+1] = pts[1]
  polyline(pts, color)
  if pause_bars then
    local bar_h = math.floor(size * 0.24)
    local bar_w = math.max(3, math.floor(size * 0.08))
    local gap   = math.max(2, math.floor(size * 0.07))
    frame.display.rect(cx - gap - bar_w, cy - bar_h, bar_w, bar_h * 2, color, true)
    frame.display.rect(cx + gap,          cy - bar_h, bar_w, bar_h * 2, color, true)
  end
end

--- APPROX: point_cloud_text
--- True per-pixel particle rendering is not feasible in Lua.
--- Approximation: render the text normally.
local function point_cloud_text(text, cx, cy, font_size, density, color)
  if not HAS_FRAME then return end
  if density and density < 0.05 then return end
  frame.display.text(text, cx, cy, color)
end

-- ---------------------------------------------------------------------------
-- Build the halo compatibility table
-- ---------------------------------------------------------------------------
local halo = {}

if HAS_FRAME then
  -- ---- display ----
  halo.display = {
    -- Core frame.display passthrough
    clear          = function(color) frame.display.clear(color or 0x000000) end,
    show           = function() frame.display.show() end,
    text           = function(txt, x, y, color) frame.display.text(txt, x, y, color) end,
    line           = function(x0,y0,x1,y1,color) frame.display.line(x0,y0,x1,y1,color) end,
    rect           = function(x,y,w,h,color,filled) frame.display.rect(x,y,w,h,color,filled) end,
    circle         = function(cx,cy,r,color,filled) frame.display.circle(cx,cy,r,color,filled) end,
    set_pixel      = function(x,y,color) frame.display.set_pixel(x,y,color) end,
    polygon        = function(pts, color) frame.display.polygon(pts, color) end,
    set_font       = function(fid, sz, sc) frame.display.set_font(fid, sz, sc) end,
    width          = function() return frame.display.width() end,
    height         = function() return frame.display.height() end,
    -- Primitive approximations
    bezier             = bezier,
    elliptical_arc     = elliptical_arc,
    polyline           = polyline,
    polar_segments     = polar_segments,
    radial_rays        = radial_rays,
    check_glyph        = check_glyph,
    shield_glyph       = shield_glyph,
    point_cloud_text   = point_cloud_text,
  }
  -- ---- bluetooth ----
  halo.bluetooth = {
    send             = function(s) frame.bluetooth.send(s) end,
    receive_callback = function(fn) frame.bluetooth.receive_callback(fn) end,
    -- Polled receive not in real frame API; return nil to stay safe
    receive          = function() return nil end,
  }
  -- ---- button / imu ----
  halo.button = {
    single = function(fn) frame.button.single(fn) end,
    double = function(fn) frame.button.double(fn) end,
    long   = function(fn) frame.button.long(fn) end,
  }
  halo.imu = {
    tap_callback = function(fn) frame.imu.tap_callback(fn) end,
  }
  -- ---- sleep / misc ----
  halo.sleep = function(s) frame.sleep(s) end
else
  -- Offline / CI mock
  halo.display   = mock_display
  halo.bluetooth = mock_bt
  halo.button    = mock_button
  halo.imu       = mock_imu
  halo.sleep     = function(s) end
end

_G.halo = halo
return halo
