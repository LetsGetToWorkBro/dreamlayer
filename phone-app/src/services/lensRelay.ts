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

// The spoken question for an "ask" emit is captured elsewhere (the phone's
// voice/ASR layer). It registers a provider here; the default is empty so the
// relay is inert until a capture layer is wired.
let questionProvider: () => string = () => "";

/** Let the voice layer supply the latest spoken question for `emit "ask"`. */
export function setQuestionProvider(fn: () => string): void {
  questionProvider = typeof fn === "function" ? fn : () => "";
}

/** Forward a lens emit to the Brain. Returns the Brain's reply (for "ask") or
 *  null when nothing was reachable/actionable. Never throws. */
export async function relayEmit(emit: { tag: string; id?: string }): Promise<AskResult> {
  const tag = (emit && emit.tag) || "";
  if (!tag) return null;
  const text = tag === "ask" ? questionProvider() : "";
  return useBrainStore.getState().emitLens(tag, text);
}

/** Stream a line of host text (translation / camera label / memory) into the
 *  running lens's `{slot}`. Returns whether the Brain accepted it. */
export async function feed(text: string, source = ""): Promise<boolean> {
  if (!text) return false;
  return useBrainStore.getState().feedLens(text, source);
}
