-- app/events.lua  (stub)
-- Event constant table used by main.lua and state_machine.lua
local E = {}
E.EVENTS = {
  startup          = "startup",
  single_click     = "single_click",
  double_click     = "double_click",
  long_press       = "long_press",
  imu_tap          = "imu_tap",
  host_connected   = "host_connected",
  host_disconnected= "host_disconnected",
  card_received    = "card_received",
  command_received = "command_received",
  low_battery      = "low_battery",
  sleep            = "sleep",
  wake             = "wake",
}
return E
