--- display/renderer.lua
--- Orchestrates the full frame render pipeline for the 256×256 circular
--- display.  Downstream modules (cards.lua, animations.lua) push draw
--- commands here; renderer dispatches them to the frame.draw* primitives
--- in the correct Z-order.
---
--- On-device: frame.draw* calls are evaluated each tick in love.draw().
--- Emulator: the Python renderer.py mirrors this logic via Pillow.

local renderer = {}

--- Draw command queue for the current frame.
local _queue = {}

--- Z-layer constants (lower = drawn first = behind)
renderer.LAYER_BG      = 0
renderer.LAYER_CONTENT = 10
renderer.LAYER_OVERLAY = 20
renderer.LAYER_HUD     = 30

--- Push a draw command onto the queue.
--- @param layer number    Z-layer constant
--- @param fn    function  Called with no args during flush()
function renderer.push(layer, fn)
    _queue[#_queue + 1] = { layer = layer, fn = fn }
end

--- Clear the draw queue (call at the start of each frame).
function renderer.clear()
    _queue = {}
end

--- Flush the queue: sort by layer, then execute each draw command.
function renderer.flush()
    table.sort(_queue, function(a, b) return a.layer < b.layer end)
    for _, cmd in ipairs(_queue) do
        cmd.fn()
    end
end

--- Fill the background with the palette background color.
--- @param color table  {r, g, b} normalised 0-1 values
function renderer.fill_bg(color)
    renderer.push(renderer.LAYER_BG, function()
        frame.display.bitmap("background", color[1], color[2], color[3])
    end)
end

--- Draw a quadratic Bézier curve.
--- @param p0         table   {x, y} start point
--- @param p1         table   {x, y} control point
--- @param p2         table   {x, y} end point
--- @param stroke     number  line width in pixels
--- @param color      table   {r, g, b, a} normalised 0-1
--- @param dash_offset number  offset into dash pattern (0 = solid)
function renderer.draw_quadratic_bezier(p0, p1, p2, stroke, color, dash_offset)
    dash_offset = dash_offset or 0
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.bezier_quad(p0, p1, p2, stroke, color, dash_offset)
    end)
end

--- Draw a polyline through a list of points.
--- @param points     table   array of {x, y} tables
--- @param stroke     number  line width in pixels
--- @param color      table   {r, g, b, a} normalised 0-1
--- @param progressive number  0.0–1.0 draw fraction (1.0 = full)
function renderer.draw_polyline(points, stroke, color, progressive)
    progressive = progressive or 1.0
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.polyline(points, stroke, color, progressive)
    end)
end

--- Draw an elliptical arc segment.
--- @param cx         number  center x
--- @param cy         number  center y
--- @param rx         number  horizontal radius
--- @param ry         number  vertical radius
--- @param start_deg  number  start angle in degrees
--- @param sweep_deg  number  arc sweep in degrees
--- @param stroke     number  line width in pixels
--- @param color      table   {r, g, b, a} normalised 0-1
--- @param rotation   number  rotation of ellipse in degrees (default 0)
function renderer.draw_elliptical_arc(cx, cy, rx, ry, start_deg, sweep_deg, stroke, color, rotation)
    rotation = rotation or 0
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.elliptical_arc(cx, cy, rx, ry, start_deg, sweep_deg, stroke, color, rotation)
    end)
end

--- Draw a check glyph (single-stroke checkmark).
--- @param center     table   {x, y} center point
--- @param size       number  bounding box size in pixels
--- @param stroke     number  line width in pixels
--- @param color      table   {r, g, b, a} normalised 0-1
--- @param progressive number  0.0–1.0 draw fraction
function renderer.draw_check_glyph(center, size, stroke, color, progressive)
    progressive = progressive or 1.0
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.check_glyph(center, size, stroke, color, progressive)
    end)
end

--- Draw a shield glyph (rounded hexagon with optional pause bars).
--- @param center     table   {x, y} center point
--- @param size       number  bounding box size in pixels
--- @param stroke     number  line width in pixels
--- @param color      table   {r, g, b, a} normalised 0-1
--- @param pause_bars boolean  draw inner pause bars (default true)
function renderer.draw_shield_glyph(center, size, stroke, color, pause_bars)
    if pause_bars == nil then pause_bars = true end
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.shield_glyph(center, size, stroke, color, pause_bars)
    end)
end

--- Draw a ring of polar arc segments, some lit.
--- @param cx         number  center x
--- @param cy         number  center y
--- @param r_inner    number  inner radius
--- @param r_outer    number  outer radius
--- @param count      number  total number of segments
--- @param lit_indices table  array of 1-based indices to illuminate
--- @param color      table   {r, g, b, a} normalised 0-1
function renderer.draw_polar_segments(cx, cy, r_inner, r_outer, count, lit_indices, color)
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.polar_segments(cx, cy, r_inner, r_outer, count, lit_indices, color)
    end)
end

--- Draw radial rays emanating from a center point.
--- @param cx         number  center x
--- @param cy         number  center y
--- @param count      number  number of rays
--- @param lengths    table   array of ray lengths (one per ray)
--- @param color      table   {r, g, b, a} normalised 0-1
--- @param tip_bloom  boolean  draw a small bloom dot at each tip (default true)
function renderer.draw_radial_rays(cx, cy, count, lengths, color, tip_bloom)
    if tip_bloom == nil then tip_bloom = true end
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.radial_rays(cx, cy, count, lengths, color, tip_bloom)
    end)
end

--- Draw text as a point-cloud (dots), density mapped to confidence.
--- @param text       string  text to render
--- @param cx         number  center x
--- @param cy         number  center y
--- @param font_size  number  reference font size in pixels
--- @param density    number  0.0–1.0 dot density (1.0 = fully solid)
--- @param color      table   {r, g, b, a} normalised 0-1
function renderer.draw_point_cloud_text(text, cx, cy, font_size, density, color)
    renderer.push(renderer.LAYER_CONTENT, function()
        frame.display.point_cloud_text(text, cx, cy, font_size, density, color)
    end)
end

--- Generate and save the export contact sheet (4×3 grid of all card PNGs).
--- Only meaningful in the emulator/export context; no-op on device.
--- @param grid_cols  number  columns in grid (default 4)
--- @param grid_rows  number  rows in grid (default 3)
--- @param cell_padding number  padding in pixels around each cell (default 4)
function renderer.draw_contact_sheet(grid_cols, grid_rows, cell_padding)
    grid_cols   = grid_cols   or 4
    grid_rows   = grid_rows   or 3
    cell_padding = cell_padding or 4
    renderer.push(renderer.LAYER_OVERLAY, function()
        frame.display.contact_sheet(grid_cols, grid_rows, cell_padding)
    end)
end

return renderer
