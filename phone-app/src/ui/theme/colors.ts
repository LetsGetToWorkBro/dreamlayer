/**
 * colors.ts — the DreamLayer "Platinum" palette (Mac OS 8.1, on the phone).
 *
 * The token KEYS are the app-wide contract every screen reads by name; only
 * their VALUES moved from the old luminous-HUD dark world to the Platinum light
 * world — a grey pinstripe desktop, light-grey control faces, white content
 * wells, black ink, and the deep brand teal that stays legible on light. Nothing
 * that consumes `colors.*` changes shape, so the whole app reskins from here.
 *
 * `platinum` carries the extra materials the chrome needs — bevel highlight /
 * shadow lines, the desktop and title-bar pinstripes, the hard 1px frame — kept
 * off `ColorToken` on purpose so screens keep reaching for semantic tokens, not
 * raw materials.
 */
export const colors = {
  background:       "#B8B8B8",  // the Platinum desktop behind every window
  surface:          "#DDDDDD",  // window / control face (the 3D grey)
  surfaceElevated:  "#FFFFFF",  // white content wells, inputs, list rows
  textPrimary:      "#141414",  // ink — titles, answers
  textSecondary:    "#4A5054",  // secondary ink — captions, supporting copy
  accentMemory:     "#0B6B52",  // deep brand teal — legible on light; "on"
  accentAttention:  "#B3402E",  // coral ink — promises, incognito, "look here"
  accentSuccess:    "#1E7A3C",  // confirmations, live (darkened for light bg)
  accentError:      "#B3302A",  // destructive, unsigned
  borderSubtle:     "#8E8E8E",  // the bevel-shadow line / hairline frame
  statusPaused:     "#6B7A82",  // muted / disabled
  shimmer:          "#C9C9C9",  // loading wash on light
} as const;
export type ColorToken = keyof typeof colors;

/**
 * platinum — the raw Mac OS 8.1 materials for the chrome primitives (Card,
 * ScreenHeader, the tab bar, buttons). Screens should keep using `colors.*`;
 * these are for building bevels and pinstripes.
 */
export const platinum = {
  desk:     "#B8B8B8",   // desktop base (pinstriped over)
  deskLine: "#A6A6A6",   // the darker line in the desktop pinstripe
  paper:    "#EFEFEF",   // lightest panel / menu paper
  face:     "#DDDDDD",   // window & control face
  face2:    "#CCCCCC",   // a step down (button gradient bottom)
  faceHi:   "#F6F6F6",   // a step up (button gradient top)
  well:     "#FFFFFF",   // white content well
  hi:       "#FFFFFF",   // bevel highlight (top-left)
  sh:       "#8E8E8E",   // bevel shadow (bottom-right)
  dk:       "#4A4A4A",   // deep shadow
  frame:    "#000000",   // hard 1px window frame
  ink:      "#141414",
  ink2:     "#4A5054",
  ink3:     "#7A8288",   // dimmest ink (menu disabled)
  tealInk:  "#0B6B52",   // deep teal, text-safe on light
  teal:     "#2FD4C4",   // bright teal, only on dark chips
  coralInk: "#B3402E",
  menuHi:   "#333399",   // classic menu-selection blue
  // title-bar pinstripe stops (light → mid → dark), 1px each
  stripe:   ["#FFFFFF", "#DDDDDD", "#ACACAC"] as const,
} as const;

/**
 * Halo Cinema v1 — exact mirror of the glasses palette
 * (halo-lua/display/palette.lua / hud/themes.py). CardPreview and
 * DreamCanvas draw with THESE tokens so the phone preview is the QA
 * truth: if the phone and the glasses diverge, one of them is wrong.
 * The HUD is its own dark world and does NOT follow the Platinum reskin.
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
