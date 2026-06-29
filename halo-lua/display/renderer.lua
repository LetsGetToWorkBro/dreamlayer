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
--- @param layer number  Z-layer constant
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

return renderer
