/**
 * haptics.ts — a thin, always-safe wrapper around expo-haptics.
 *
 * Every tap on a primary surface, every successful pair, every warning gets a
 * matching physical tick. We load expo-haptics lazily and swallow anything that
 * throws, so the app runs identically on web, in tests, or on a device without
 * the native module — the haptics are pure polish, never a dependency.
 */
let Haptics: any = null;
let tried = false;

function mod(): any {
  if (!tried) {
    tried = true;
    try {
      // require, not import, so a missing native module never breaks the bundle
      Haptics = require("expo-haptics");
    } catch {
      Haptics = null;
    }
  }
  return Haptics;
}

/** A light tick — the default feel for buttons, chips, toggles. */
export function tapLight(): void {
  const h = mod();
  try {
    h?.impactAsync?.(h.ImpactFeedbackStyle.Light);
  } catch {
    /* no haptics here — ignore */
  }
}

/** A firmer tick for weightier actions (pair, send, confirm). */
export function tapMedium(): void {
  const h = mod();
  try {
    h?.impactAsync?.(h.ImpactFeedbackStyle.Medium);
  } catch {
    /* ignore */
  }
}

/** The success chime — a pair landed, a reply sent. */
export function tapSuccess(): void {
  const h = mod();
  try {
    h?.notificationAsync?.(h.NotificationFeedbackType.Success);
  } catch {
    /* ignore */
  }
}

/** A warning buzz — a code didn't parse, a send failed. */
export function tapWarn(): void {
  const h = mod();
  try {
    h?.notificationAsync?.(h.NotificationFeedbackType.Warning);
  } catch {
    /* ignore */
  }
}
