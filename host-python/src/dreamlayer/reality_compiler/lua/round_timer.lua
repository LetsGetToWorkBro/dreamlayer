-- round_timer.lua  (Reality Compiler reference — not used directly by codegen)
-- Canonical hand-written reference for the round_timer behavior.
-- CodeGenerator fills in the string.Template version from template_library.py.

local DURATION    = 180
local OVERTIME    = 30
local WARN_AT     = 10
local running     = false

local function show_time(secs, label)
    frame.display.text(label or "", 10, 40)
    frame.display.text(tostring(secs), 10, 80)
    frame.display.show()
end

frame.button.double_click(function()
    if running then running = false; return end
    running = true
    local remaining = DURATION
    while running and remaining > 0 do
        show_time(remaining, "ROUND")
        frame.sleep(1.0)
        remaining = remaining - 1
    end
    if running and OVERTIME > 0 then
        remaining = OVERTIME
        while running and remaining > 0 do
            show_time(remaining, "OT")
            frame.sleep(1.0)
            remaining = remaining - 1
        end
    end
    running = false
    frame.display.text("OVER", 10, 80)
    frame.display.show()
end)

frame.display.text("Double-tap: start", 10, 80)
frame.display.show()
while true do frame.sleep(0.5) end
