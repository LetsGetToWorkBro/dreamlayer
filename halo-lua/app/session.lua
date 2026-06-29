-- app/session.lua  (stub)
-- Tracks session start/end timestamps.
local M = { _start = nil }
function M.start(ts)  M._start = ts end
function M.end_session() M._start = nil end
function M.active()   return M._start ~= nil end
return M
