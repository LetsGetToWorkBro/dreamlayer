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
CONFIDENCE_HIGH   = 0xB8FFE9  # Meridian: retired the off-family violet
PRIVACY_DANGER    = 0xFF4444
PRIVACY_CAUTION   = 0xFF8800
WARNING_AMBER     = 0xFF6600

# --- Meridian Solid (docs/cinema_v2/solid.md) ---
# ACCENT_MEMORY / TEXT_GHOST are dynamic-slot bases (fx / ghost_text):
# static ramps and fills use the one-LSB static twin + dim twins instead.
ACCENT_MEMORY_STATIC = 0x2CC79B
ACCENT_SUCCESS_DIM   = 0x2E7A3C
ACCENT_ATTENTION_DIM = 0x7A3A2C
WARNING_AMBER_DIM    = 0x8A3A00
# GHOST_WHITE: if your renderer takes color+alpha separately, use 0xFFFFFF and pass alpha=0.03 (8/255)
# If it packs ARGB into one int with alpha in top byte: 0x08FFFFFF
GHOST_WHITE       = 0xFFFFFF

# --- Meridian: dynamic palette slot bank (mirrors palette.lua) ---
# Slots 1-6 are runtime-reassignable via {t:"palette"} frames /
# frame.display.assign_color_ycbcr. Slot 0 and 7-15 are static.
# Air tier: sky/energy/drift_*; Ghost tier: ghost_text; fx is shared
# (Truth Ripple warm pulse, DeviationAlert ring). The v1 prism-fringe
# aliases on the drift slots are gone (CINEMA_V2_DELTAS.md §2): every
# slot has exactly one owner.
DYNAMIC_SLOTS = {
    "sky":        1,
    "energy":     2,
    "drift_a":    3,
    "drift_b":    4,
    "ghost_text": 5,
    "fx":         6,
}


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
