-- system/settings.lua  (stub)
local M = { _file = nil, _data = {} }
local DEFAULTS = { reduce_motion = false, capture_interval_ms = 4000 }
function M.bind(file_api) M._file = file_api end
function M.load()
  if not M._file then M._data = {}; return end
  local ok, raw = pcall(function() return M._file.read("settings.json") end)
  if ok and raw then
    local jok, parsed = pcall(function()
      if _G.halo and _G.halo.json then return _G.halo.json.decode(raw) end
      return {}
    end)
    if jok and parsed then M._data = parsed; return end
  end
  M._data = {}
end
function M.get(key) return M._data[key] ~= nil and M._data[key] or DEFAULTS[key] end
function M.set(key, val) M._data[key] = val end
return M
