-- app/commands.lua  (stub)
-- Handles inbound command messages dispatched from host_comm.on_message.
local host_comm = require("ble.host_comm")
local MT        = require("ble.message_types")
local M = {}
function M.init(state_machine, renderer)
  M._sm = state_machine; M._r = renderer
  host_comm.register(MT.COMMAND, function(msg)
    -- Forward to state machine as a generic command event
    if M._sm then M._sm.dispatch(msg.kind or MT.EVENT) end
  end)
end
return M
