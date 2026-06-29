-- capture/microphone.lua  (stub)
local M = {}
function M.bind(mic_api) M._api = mic_api end
function M.start(cb)     if M._api and M._api.start then M._api.start(cb) end end
function M.stop()        if M._api and M._api.stop  then M._api.stop()   end end
return M
