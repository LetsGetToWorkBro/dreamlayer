"""themes.py — Python mirror of halo-lua/display/palette.lua."""

BACKGROUND        = 0x000000
SURFACE           = 0x0E1416

TEXT_PRIMARY      = 0xECF0F1
TEXT_SECONDARY    = 0xA8B8C0
TEXT_GHOST        = 0x58686F

ACCENT_MEMORY     = 0x2CC79A
ACCENT_MEMORY_DIM = 0x1A7A60
MEMORY_RAIL       = 0x2CC79A

ACCENT_ATTENTION  = 0xE06B52
ACCENT_SUCCESS    = 0x56D364
ACCENT_ERROR      = 0xE05252

BORDER_SUBTLE     = 0x2A3C44
STATUS_PAUSED     = 0x8FA8B2

# --- New palette additions (transformative pass) ---
MEMORY_TRACE      = 0x00FFAA
CONFIDENCE_LOW    = 0xFFAA00
CONFIDENCE_MED    = 0x00FFAA
CONFIDENCE_HIGH   = 0xAA00FF
PRIVACY_DANGER    = 0xFF4444
PRIVACY_CAUTION   = 0xFF8800
WARNING_AMBER     = 0xFF6600
GHOST_WHITE       = 0xFFFFFF  # use with very low alpha (8)


def to_rgb(hexval: int) -> tuple[int, int, int]:
    return ((hexval >> 16) & 0xFF, (hexval >> 8) & 0xFF, hexval & 0xFF)


def to_rgba(hexval: int, alpha: float = 1.0) -> tuple[int, int, int, int]:
    r, g, b = to_rgb(hexval)
    return (r, g, b, int(alpha * 255))


def conf_color(confidence: float | None) -> int:
    if confidence is None:
        return TEXT_GHOST
    if confidence >= 0.75:
        return CONFIDENCE_HIGH
    if confidence >= 0.40:
        return CONFIDENCE_MED
    return CONFIDENCE_LOW
