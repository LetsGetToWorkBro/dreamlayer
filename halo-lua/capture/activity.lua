-- capture/activity.lua  (stub)
-- Detects conversation/activity windows from IMU + mic energy.
local M = { _active = false }
function M.update(imu, energy) M._active = (energy or 0) > 0.15 end
function M.is_active() return M._active end
return M
