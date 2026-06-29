-- capture/camera.lua  (stub)
local M = {}
function M.bind(cam_api) M._api = cam_api end
function M.capture(cb)   if M._api and M._api.capture then M._api.capture(cb) end end
return M
