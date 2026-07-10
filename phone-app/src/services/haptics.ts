/**
 * haptics.ts — the DreamLayer haptic vocabulary.
 *
 * The glasses have no actuator, so the phone is the haptic body (on-glass
 * earcons are the sibling channel — see docs/gitbook/reference/earcons).
 * One data-driven map, one grammar: weight x pattern x repetition. Rules:
 *
 *   - L0 ambient never buzzes — the rim glow is the channel.
 *   - lens signatures never reuse system patterns.
 *   - L3 is the ONLY repeater (the caller re-fires it; nothing loops here).
 *   - every pattern <= ~400 ms, so a pocket never feels like a pager.
 *   - answer-ahead is silent BY DESIGN (matches answer_ahead.py).
 *
 * expo-haptics loads lazily and everything is try/catch-swallowed, so web,
 * tests, and devices without the native module are silent no-ops.
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

/** One beat of a pattern: an impact weight or a notification type. */
export type Beat =
  | { impact: "light" | "medium" | "heavy"; at: number }
  | { notify: "success" | "warning" | "error"; at: number };

/** The vocabulary. `at` is milliseconds from pattern start. */
export type HapticSignal =
  // system grammar
  | "confirm"          // 1x light — every Tappable press (exists everywhere)
  | "action"           // 1x medium — weightier actions (pair, send, confirm)
  | "success"          // pair landed, reply sent
  | "warn"             // code didn't parse, send failed
  | "notice"           // L1: new message card, brief ready
  | "attention"        // L2: commitment drifting, person-you-owe in view
  | "interrupt"        // L3: "Listen!" — the only signal a caller may re-fire
  // the Veil — must be unmistakable and unique in both directions
  | "veil_on"          // descending: going deliberately deaf and blind
  | "veil_off"         // ascending: eyes open again
  // lens signatures
  | "commitment_crack" // 2x heavy, slow — something broke
  | "commitment_bloom" // 3x light ascending — something healed
  | "truth_flag"       // sharp - pause - sharp; private, never an earcon
  | "figment_deployed" // rehearsal kept + live on the stage
  | "answer_ahead";    // SILENT by design

export const PATTERNS: Record<HapticSignal, Beat[]> = {
  confirm: [{ impact: "light", at: 0 }],
  action: [{ impact: "medium", at: 0 }],
  success: [{ notify: "success", at: 0 }],
  warn: [{ notify: "warning", at: 0 }],
  notice: [{ impact: "light", at: 0 }],
  attention: [{ impact: "medium", at: 0 }, { impact: "medium", at: 120 }],
  interrupt: [{ impact: "heavy", at: 0 }, { notify: "error", at: 90 }],
  veil_on: [
    { impact: "heavy", at: 0 },
    { impact: "medium", at: 140 },
    { impact: "light", at: 280 },
  ],
  veil_off: [
    { impact: "light", at: 0 },
    { impact: "medium", at: 140 },
    { impact: "heavy", at: 280 },
  ],
  commitment_crack: [{ impact: "heavy", at: 0 }, { impact: "heavy", at: 250 }],
  commitment_bloom: [
    { impact: "light", at: 0 },
    { impact: "light", at: 110 },
    { impact: "medium", at: 220 },
  ],
  truth_flag: [{ impact: "heavy", at: 0 }, { impact: "heavy", at: 320 }],
  figment_deployed: [{ impact: "medium", at: 0 }, { notify: "success", at: 150 }],
  answer_ahead: [],
};

function fire(beat: Beat): void {
  const h = mod();
  if (!h) return;
  try {
    if ("impact" in beat) {
      const style = { light: h.ImpactFeedbackStyle?.Light,
                      medium: h.ImpactFeedbackStyle?.Medium,
                      heavy: h.ImpactFeedbackStyle?.Heavy }[beat.impact];
      h.impactAsync?.(style);
    } else {
      const type = { success: h.NotificationFeedbackType?.Success,
                     warning: h.NotificationFeedbackType?.Warning,
                     error: h.NotificationFeedbackType?.Error }[beat.notify];
      h.notificationAsync?.(type);
    }
  } catch {
    /* no haptics here — ignore */
  }
}

/** Play a vocabulary signal. Timed beats run on setTimeout chains; an empty
 * pattern (answer_ahead) is a deliberate no-op. */
export function play(signal: HapticSignal): void {
  const beats = resolve(signal);
  for (const beat of beats) {
    if (beat.at === 0) fire(beat);
    else setTimeout(() => fire(beat), beat.at);
  }
}

// --- Earcon/Haptic Packs (B8): a selected pack may reskin the feel. The pack
// picker installs an override table here; play() consults it before the
// built-in vocabulary. answer_ahead stays silent by construction (the pack
// gate rejects a non-empty answer_ahead), so an override can't make it buzz.
let _overrides: Partial<Record<HapticSignal, Beat[]>> | null = null;

export function setHapticOverrides(map: Partial<Record<HapticSignal, Beat[]>> | null): void {
  _overrides = map;
}

function resolve(signal: HapticSignal): Beat[] {
  const o = _overrides && _overrides[signal];
  return o ?? PATTERNS[signal] ?? [];
}

/**
 * TinCan: the message IS the pattern — replay the sender's recorded tap
 * rhythm (ms offsets from start), clamped to 6 taps / 1.5 s so a mash can't
 * become a pager. Poetic and functional: no new vocabulary to learn, you
 * feel *their* rhythm.
 */
export function playTinCan(tapOffsetsMs: number[]): void {
  const taps = (tapOffsetsMs ?? []).slice(0, 6);
  for (const at of taps) {
    const t = Math.max(0, Math.min(1500, at));
    if (t === 0) fire({ impact: "medium", at: 0 });
    else setTimeout(() => fire({ impact: "medium", at: t }), t);
  }
}

// ---------------------------------------------------------------------------
// Legacy surface — the four originals, now vocabulary entries. Call sites
// (Tappable, onboarding, brain) keep working unchanged.
// ---------------------------------------------------------------------------

/** A light tick — the default feel for buttons, chips, toggles. */
export function tapLight(): void {
  play("confirm");
}

/** A firmer tick for weightier actions (pair, send, confirm). */
export function tapMedium(): void {
  play("action");
}

/** The success chime — a pair landed, a reply sent. */
export function tapSuccess(): void {
  play("success");
}

/** A warning buzz — a code didn't parse, a send failed. */
export function tapWarn(): void {
  play("warn");
}
