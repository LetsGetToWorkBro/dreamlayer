-- ble/host_comm.lua
-- Manages the BLE channel between Halo and the Python host.
--
-- Two public entry-points:
--   on_receive(raw)   -- called with raw bytes/string from halo.bluetooth.receive()
--                        Feeds the framing reassembler; returns a decoded table when
--                        a complete message has been received, or nil if still buffering.
--   on_message(msg)   -- called with an already-decoded table for message types that
--                        are NOT handled by main.lua's process_inbound dispatch
--                        (i.e. card payloads, command payloads, etc.).
--
-- Framing: real_bridge.py prepends a 4-byte big-endian total-length header
-- (including the 4-byte header itself) before each JSON envelope, then fragments
-- over BLE MTU.  protocol.lua handles reassembly.

local protocol = require("ble.protocol")
local MT       = require("ble.message_types")

local M = {}

-- Bound halo.bluetooth table (set by main.lua via M.bind)
local _bt = nil

-- Handler registry: type-string -> function(msg)
local _handlers = {}

-- ---------------------------------------------------------------------------
-- bind(bluetooth_api)
-- Called by main.lua before the tick loop starts.
-- ---------------------------------------------------------------------------
function M.bind(bluetooth_api)
  _bt = bluetooth_api
end

-- ---------------------------------------------------------------------------
-- register(msg_type, handler)
-- Register a handler for a decoded message type constant from message_types.
-- handler receives the full decoded table.
-- ---------------------------------------------------------------------------
function M.register(msg_type, handler)
  _handlers[msg_type] = handler
end

-- ---------------------------------------------------------------------------
-- on_receive(raw)
-- Feed raw bytes from halo.bluetooth.receive() into the reassembler.
-- Returns the decoded message table when a complete frame has been reassembled,
-- or nil while still accumulating fragments.
-- ---------------------------------------------------------------------------
function M.on_receive(raw)
  if not raw or raw == "" then return nil end
  local complete = protocol.feed(raw)
  if not complete then return nil end
  -- complete is a JSON string; decode it
  local ok, msg = pcall(M._decode, complete)
  if not ok then
    -- malformed JSON — log and discard
    if _G.halo and _G.halo.log then
      _G.halo.log("[host_comm] JSON decode error: " .. tostring(msg))
    end
    return nil
  end
  return msg
end

-- ---------------------------------------------------------------------------
-- on_message(msg)
-- Dispatch an already-decoded message table to registered handlers.
-- Called by main.lua for types not handled in process_inbound().
-- ---------------------------------------------------------------------------
function M.on_message(msg)
  if not msg or not msg.t then return end
  local handler = _handlers[msg.t]
  if handler then
    handler(msg)
  end
  -- Also dispatch to a catch-all "*" handler if registered
  local catch = _handlers["*"]
  if catch then catch(msg) end
end

-- ---------------------------------------------------------------------------
-- send(tbl)
-- Encode tbl as JSON, frame it with the 4-byte length prefix, and send
-- via halo.bluetooth.  Only available after bind().
-- ---------------------------------------------------------------------------
function M.send(tbl)
  if not _bt then return end
  local json = M._encode(tbl)
  local framed = protocol.frame(json)
  if _bt.send then
    _bt.send(framed)
  end
end

-- ---------------------------------------------------------------------------
-- Internal: minimal JSON encode / decode
-- Halo Lua runtime ships a tiny cjson-compatible table at halo.json,
-- or we fall back to a lightweight hand-rolled encoder for simple tables.
-- ---------------------------------------------------------------------------
function M._decode(s)
  if _G.halo and _G.halo.json and _G.halo.json.decode then
    return _G.halo.json.decode(s)
  end
  -- Fallback: require lib.json if available
  local ok, json = pcall(require, "lib.json")
  if ok then return json.decode(s) end
  error("No JSON decoder available")
end

function M._encode(t)
  if _G.halo and _G.halo.json and _G.halo.json.encode then
    return _G.halo.json.encode(t)
  end
  local ok, json = pcall(require, "lib.json")
  if ok then return json.encode(t) end
  error("No JSON encoder available")
end

return M
