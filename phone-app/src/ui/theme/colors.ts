export const colors = {
  background:       "#000000",
  surface:          "#0E1416",
  surfaceElevated:  "#141F23",
  textPrimary:      "#FFFFFF",
  textSecondary:    "#8A9BA3",
  accentMemory:     "#2FD4C4",
  accentAttention:  "#FF6B5E",
  accentSuccess:    "#56D364",
  accentError:      "#FF5C5C",
  borderSubtle:     "#1F2A2E",
  statusPaused:     "#6B7A82",
  shimmer:          "#1A2830",
} as const;
export type ColorToken = keyof typeof colors;

/**
 * Halo Cinema v1 — exact mirror of the glasses palette
 * (halo-lua/display/palette.lua / hud/themes.py). CardPreview and
 * DreamCanvas draw with THESE tokens so the phone preview is the QA
 * truth: if the phone and the glasses diverge, one of them is wrong.
 */
export const haloPalette = {
  background:      "#000000",
  surface:         "#0E1416",
  textPrimary:     "#ECF0F1",
  textSecondary:   "#A8B8C0",
  textGhost:       "#58686F",
  accentMemory:    "#2CC79A",
  accentMemoryDim: "#1A7A60",
  accentAttention: "#E06B52",
  accentSuccess:   "#56D364",
  accentError:     "#E05252",
  borderSubtle:    "#2A3C44",
  statusPaused:    "#8FA8B2",
  memoryTrace:     "#00FFAA",
  confidenceLow:   "#FFAA00",
  confidenceMed:   "#00FFAA",
  confidenceHigh:  "#B8FFE9", // Meridian: retired the off-family violet
  privacyDanger:   "#FF4444",
  privacyCaution:  "#FF8800",
  warningAmber:    "#FF6600",
} as const;
export type HaloColorToken = keyof typeof haloPalette;
