/**
 * lensRelay — closes the glass → Brain → glass loop on the phone side.
 *
 * A lens (a figment) runs on the glasses; when it emits a rate-limited tag the
 * BLE bridge routes it here, and we forward it to the paired Brain
 * (`POST /dreamlayer/rc/emit`) so the Brain can act and stream the result back
 * onto the glass. `emit "ask"` runs the Brain over the spoken question; other
 * tags carry a payload straight to the lens's `{slot}`.
 *
 * The world-facing showcases — Whisper (translation), Second Sight (a camera
 * label), Ember (a resurfaced memory) — push host text into the running lens's
 * slot via `feed()`.
 *
 * This module is the *conduit*, not the capture: ASR, vision and translation
 * live in their own layers and call `feed()` / `setQuestionProvider()`; the
 * relay only moves bytes. That keeps it pure-TS and unit-testable with a fake
 * Brain, exactly like the BLE core.
 */
import { useBrainStore, type AskResult } from "../state/useBrainStore";
import { useVitalsStore } from "../state/useVitalsStore";

// The spoken question for an "ask" emit is captured elsewhere (the phone's
// voice/ASR layer). It registers a provider here; the default is empty so the
// relay is inert until a capture layer is wired.
let questionProvider: () => string = () => "";

/** Let the voice layer supply the latest spoken question for `emit "ask"`. */
export function setQuestionProvider(fn: () => string): void {
  questionProvider = typeof fn === "function" ? fn : () => "";
}

/** Is capture suppressed right now? The relay must refuse captured content when
 *  the wearer has closed the Veil from EITHER end:
 *   • the phone/session (`capturePaused` — also forced on by local incognito,
 *     set synchronously by setIncognito so it is authoritative the instant the
 *     switch flips, not after the Brain acks the deferred config push), and
 *   • the glasses hardware (a PRIVACY_VEIL telemetry frame flips
 *     useVitalsStore.veiled; PRIVACY_RESUMED clears it). Trusting only the phone
 *     switch left a window where a Veil raised on the glass still relayed the
 *     spoken question — this closes it (audit 2026-07-14). */
function captureSuppressed(): boolean {
  return useBrainStore.getState().capturePaused || useVitalsStore.getState().veiled;
}

/** Forward a lens emit to the Brain. Returns the Brain's reply (for "ask") or
 *  null when nothing was reachable/actionable. Never throws.
 *
 *  Veil-enforcing chokepoint (audit 2026-07-14): the `emit "ask"` payload is the
 *  wearer's spoken question — captured speech — so while capture is suppressed
 *  from either end (the phone Veil / incognito's capturePaused, or a Veil raised
 *  on the glasses → vitals.veiled) the phone refuses to forward it rather than
 *  trusting the upstream ASR layer to have stopped. Other tags carry no captured
 *  payload and are inert lens control signals. */
export async function relayEmit(emit: { tag: string; id?: string }): Promise<AskResult> {
  const tag = (emit && emit.tag) || "";
  if (!tag) return null;
  if (tag === "ask" && captureSuppressed()) return null;
  const text = tag === "ask" ? questionProvider() : "";
  return useBrainStore.getState().emitLens(tag, text);
}

/** Stream a line of host text (translation / camera label / memory) into the
 *  running lens's `{slot}`. Returns whether the Brain accepted it.
 *
 *  Veil-gated: this text is host capture (translated speech, a camera label, a
 *  resurfaced memory), so the Veil / incognito — from the phone OR the glasses —
 *  silences it here on the phone. */
export async function feed(text: string, source = ""): Promise<boolean> {
  if (!text) return false;
  if (captureSuppressed()) return false;
  return useBrainStore.getState().feedLens(text, source);
}
