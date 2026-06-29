local M = {}

M.background        = 0x000000
M.surface           = 0x0E1416

M.text_primary      = 0xECF0F1
M.text_secondary    = 0xA8B8C0
M.text_ghost        = 0x58686F

M.accent_memory     = 0x2CC79A
M.accent_memory_dim = 0x1A7A60
M.memory_rail       = 0x2CC79A

M.accent_attention  = 0xE06B52
M.accent_success    = 0x56D364
M.accent_error      = 0xE05252

M.border_subtle     = 0x2A3C44
M.status_paused     = 0x8FA8B2

-- New AAA visual pass additions
M.memory_trace      = 0x00FFAA
M.confidence_low    = 0xFFAA00
M.confidence_med    = 0x00FFAA
M.confidence_high   = 0xAA00FF
M.privacy_danger    = 0xFF4444
M.privacy_caution   = 0xFF8800
M.warning_amber     = 0xFF6600
M.ghost_white       = 0xFFFFFF  -- use with alpha separately; Lua hex can't encode alpha in one literal

return M
