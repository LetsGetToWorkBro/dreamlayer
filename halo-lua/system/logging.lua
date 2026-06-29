-- system/logging.lua  (stub)
local M = {}
local _fn = nil
function M.bind(log_fn) _fn = log_fn end
function M.info(s)  if _fn then _fn("[INFO] "  .. s) elseif print then print("[INFO] "  .. s) end end
function M.warn(s)  if _fn then _fn("[WARN] "  .. s) elseif print then print("[WARN] "  .. s) end end
function M.error(s) if _fn then _fn("[ERROR] " .. s) elseif print then print("[ERROR] " .. s) end end
return M
