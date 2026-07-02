/**
 * spacing.ts — one rhythm for the whole app.
 *
 * An 8-point scale (with a 4 half-step) so every margin, gap, and pad lands
 * on the same grid. Radii and a small elevation ramp live here too, so cards,
 * pills, and sheets feel like one material.
 */
export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
  huge: 48,
} as const;

export const radius = {
  sm: 10,
  md: 14,
  lg: 18,
  xl: 24,
  pill: 999,
} as const;

/** Screen gutter — the single horizontal inset every screen shares. */
export const gutter = space.xxl;

export type Space = keyof typeof space;
