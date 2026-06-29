-- app/state_machine.lua  (stub)
-- Full FSM implementation lives here on device build.
-- Provides: init(renderer, scheduler, on_transition), dispatch(event), state()
local M = { _state = "boot" }
function M.init(renderer, scheduler, on_transition)
  M._renderer = renderer; M._scheduler = scheduler; M._on_transition = on_transition
  M._state = "ready"
end
function M.dispatch(ev)
  if M._on_transition then M._on_transition(M._state, M._state, ev) end
end
function M.state() return M._state end
return M
