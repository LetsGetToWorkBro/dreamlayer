export const motion = {
  instant: 100,
  fast: 180,
  base: 240,
  slow: 400,
  breath: 2400,
  onboarding: 500,
  easeOut: "cubic-bezier(0.16, 1, 0.3, 1)" as const,
  reduceMotion: false,
};

/**
 * Halo Cinema v1 motion signatures — timing parity with the glasses.
 * Mirrors halo-lua/display/animations.lua (SIG_* constants). RN screens
 * breathe the same rhythm as the HUD: if a value changes there, change it
 * here (docs/HALO_CINEMA_V1.md §1.1).
 */
export const signatures = {
  irisBloom:   { duration: 180, trail: 60,  rFrom: 112, rTo: 36 },
  ghostWake:   { duration: 320, jitterPx: 2 },
  prismSlide:  { duration: 140, splitPx: 2 },
  confidenceHalo: { period: 3200, rBase: 24, rConf: 40 },
  truthRipple: { duration: 400, rMax: 120, coldDuration: 240 },
  memoryComet: { duration: 280, tail: 3, degPerWeek: 30, maxDeg: 330 },
  // HUD acoustics analogs
  chime:  { duration: 220, rFrom: 8, rTo: 28 },
  chord:  { step: 40 },
  rumble: { duration: 100 },
} as const;

export type SignatureName = keyof typeof signatures;
