export const motion = {
  instant: 100,
  fast: 180,
  base: 240,
  slow: 400,
  breath: 2400,
  onboarding: 500,
  easeOut: "cubic-bezier(0.16, 1, 0.3, 1)" as const,
  /** The OS "reduce motion" setting, mirrored here. Read it; write it only
   * through setReduceMotion() so subscribers hear about the change. */
  reduceMotion: false,
};

/* ------------------------------------------------------- reduce motion --
 * One flag, one writer, one place to subscribe. The OS value is read once
 * (and then watched) by useReduceMotion() in ../anim — every consumer reads
 * it from here rather than calling AccessibilityInfo itself, so a test can
 * drive the whole app's motion with setReduceMotion(true) and nothing has to
 * mock react-native. */

const reduceMotionListeners = new Set<(on: boolean) => void>();

/** The single write seam for the reduce-motion flag. No-op when unchanged. */
export function setReduceMotion(on: boolean): void {
  if (motion.reduceMotion === on) return;
  motion.reduceMotion = on;
  // copy first: a listener may unsubscribe itself while we notify
  for (const fn of [...reduceMotionListeners]) fn(on);
}

/** Listen for reduce-motion changes. Returns the unsubscribe. */
export function subscribeReduceMotion(fn: (on: boolean) => void): () => void {
  reduceMotionListeners.add(fn);
  return () => {
    reduceMotionListeners.delete(fn);
  };
}

/** How long an animation may actually run for: 0 — land on the end value now —
 * when the user asked for less motion, otherwise the timing you asked for. */
export function motionDuration(ms: number): number {
  return motion.reduceMotion ? 0 : ms;
}

/**
 * Meridian motion — timing parity with the glasses.
 * Mirrors halo-lua/display/animations.lua (SIG_* / MER_* / TESTIMONY_*
 * constants). RN screens breathe the same rhythm as the HUD: if a value
 * changes there, change it here (docs/cinema_v2/focus.md, horizon.md).
 * The killed v1 signatures (iris/prism/halo-orbit/comet) are gone with
 * their replacements — see docs/CINEMA_V2_DELTAS.md §1-§4.
 */
export const signatures = {
  // the Focus law: condensation / recession
  focus: {
    travel: 140, land: 100, trail: 60,
    landRFrom: 56, landRTo: 36, ringR: 92,
    recede: 200, textCut: 0.4, xfadeLag: 40,
  },
  ghostWake:   { duration: 320, jitterPx: 2 },
  truthRipple: { duration: 400, rMax: 120, coldDuration: 240 },
  testimony:   { r: 64, slotDeg: 40, stageMs: 80, tearPx: 3 },
  // HUD acoustics analogs
  chime:  { duration: 220, rFrom: 8, rTo: 28 },
  chord:  { step: 40 },
  rumble: { duration: 100 },
} as const;

/**
 * The Horizon dial (docs/cinema_v2/horizon.md) — geometry parity with
 * halo-lua/display/animations.lua MER_* bank.
 */
export const meridian = {
  trackR: 100, markBaseR: 101, rimR: 105,
  nowDeg: -90, degPerHour: 30, windowHours: 5,
  seamFromDeg: 60, seamToDeg: 120,
  elderDeg: 58, futureCapDeg: 122,
  marksMax: 48, markMergeDeg: 3,
  markLen: [3, 6, 9] as const,          // by luma tier
  nowLenMin: 6, nowLenMax: 9,
  staleMs: 30000, arrivalPulseMs: 300, highlightMs: 2400,
  promiseR: 105, promiseSlipR: 95, promiseStackPx: 7,
} as const;

export type SignatureName = keyof typeof signatures;
