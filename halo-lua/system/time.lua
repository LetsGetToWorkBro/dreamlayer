-- system/time.lua  (stub)
local M = { _fn = nil }
function M.bind(fn) M._fn = fn end
function M.now()    return M._fn and M._fn() or 0 end
return M
