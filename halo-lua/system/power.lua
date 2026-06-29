-- system/power.lua  (stub)
local M = { _api = nil }
function M.bind(power_api) M._api = power_api end
function M.poll()
  if not M._api then return nil end
  local lvl = M._api.level and M._api.level() or nil
  if lvl and lvl < 0.10 then return "low_battery" end
  return nil
end
return M
