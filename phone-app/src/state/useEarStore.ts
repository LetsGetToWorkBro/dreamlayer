/**
 * useEarStore — the phone's control surface for everything the Brain HEARS.
 *
 * Live captions, the cross-language interpreter, the room read and Name
 * Capture all shipped with a switch on the Mac's own web panel and NOTHING on
 * the phone. The phone is the surface the wearer actually carries, so a
 * feature you can only turn on by opening a laptop is, for most of a day, a
 * feature that does not exist. This is that surface's client.
 *
 * Every switch here writes ONE route — POST /dreamlayer/config — because the
 * Brain applies these live on the way through (`_apply_interpret`,
 * `_apply_truth_lens`, `start_ear`/`stop_ear`), and Name Capture reads its two
 * flags fresh on every utterance. A config write is not a deferred setting.
 *
 * THREE THINGS THIS CLIENT MUST NOT SMOOTH OVER
 * ---------------------------------------------
 * 1. A SWITCH BEING ON IS NOT THE FEATURE WORKING. The Brain reports the
 *    persisted opt-in and the runtime fact separately — `interpret` vs
 *    `interpretProved`, `truthLens` vs `truthReads`, `listen` vs `listening` —
 *    precisely so a screen can say "on, but no microphone is open" instead of
 *    a green switch over silence. They are carried through as separate fields
 *    and never merged.
 *
 * 2. THE STATE LIVES ON THE BRAIN, NOT HERE. `useBrainStore` queues its own
 *    switches in an outbox because the phone owns them; these are the Brain's,
 *    so an unreachable Brain means the switch DOES NOT MOVE. A toggle that
 *    slides while the write fails is a lie the wearer acts on — they walk away
 *    believing the room is being read.
 *
 * 3. UNREACHABLE IS NOT OFF. `reachable: false` is its own state; a screen
 *    that draws it as a row of off switches has invented an answer.
 *
 * The Veil still wins over all of it, on the Brain, in every one of these
 * features' own gates — nothing here can talk it out of that.
 */
import { create } from "zustand";
import { useBrainStore } from "./useBrainStore";

type MacTarget = { url: string; token: string; relayUrl?: string };

function target(): MacTarget | null {
  const m = useBrainStore.getState().macMini;
  return m.connected && m.url ? { url: m.url, token: m.token, relayUrl: m.relayUrl } : null;
}

async function req(m: MacTarget, path: string, opts: RequestInit = {}): Promise<any> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (m.token) headers["X-DreamLayer-Token"] = m.token;
  const o: RequestInit = { ...opts, headers };
  try {
    return await (await fetch(m.url + path, o)).json();
  } catch (e) {
    if (m.relayUrl) return await (await fetch(m.relayUrl + path, o)).json();
    throw e;
  }
}

/** The persisted opt-ins, named as the Brain names them. Kept as one object so
 *  a write is `patch(key, value)` and the key IS the wire key — a second naming
 *  layer between a switch and a config field is one more place they can drift
 *  apart, which is how `setAnswerAhead` ended up writing nothing at all. */
export type EarSwitches = {
  listen_enabled: boolean;
  remote_listen_enabled: boolean;
  captions_enabled: boolean;
  answer_ahead_enabled: boolean;
  interpret_enabled: boolean;
  interpret_target: string;
  truth_lens_enabled: boolean;
  intro_capture_enabled: boolean;
  intro_auto_keep: boolean;
};

export const EAR_SWITCH_DEFAULTS: EarSwitches = {
  listen_enabled: false,
  remote_listen_enabled: false,
  captions_enabled: false,
  answer_ahead_enabled: false,
  interpret_enabled: false,
  interpret_target: "en",
  truth_lens_enabled: false,
  intro_capture_enabled: false,
  intro_auto_keep: false,
};

/** What the ear is actually DOING, as opposed to what it is allowed to do.
 *  Never merged into a switch: the whole point is that they can disagree. */
export type EarRuntime = {
  /** a microphone is genuinely open on the Mac */
  listening: boolean;
  /** …or the phone is streaming into one */
  remoteListening: boolean;
  heardCount: number;
  /** the interpreter pack is installed and loadable */
  canInterpret: boolean;
  /** it has produced at least one real line — the only proof that counts */
  interpretProved: boolean;
  interpretedCount: number;
  /** the room read has produced at least one real gauge */
  truthProved: boolean;
  truthReads: number;
};

export const EAR_RUNTIME_DEFAULTS: EarRuntime = {
  listening: false,
  remoteListening: false,
  heardCount: 0,
  canInterpret: false,
  interpretProved: false,
  interpretedCount: 0,
  truthProved: false,
  truthReads: 0,
};

/** Name Capture's counts — never the pending NAME. It is already on the
 *  wearer's own glass; echoing it here would put a captured name on one more
 *  surface and tell them nothing they are not looking at. */
export type IntroStatus = {
  pending: boolean;
  offered: number;
  kept: number;
};

export type EarState = {
  loaded: boolean;
  reachable: boolean;
  /** a write is in flight — the UI shows the switch as busy rather than moved */
  saving: boolean;
  /** the last write failed; the switch did NOT move */
  lastError: string;
  switches: EarSwitches;
  runtime: EarRuntime;
  intro: IntroStatus;

  refresh: () => Promise<void>;
  /** Write one Brain config key. Resolves true only if the Brain took it. */
  set: <K extends keyof EarSwitches>(key: K, value: EarSwitches[K]) => Promise<boolean>;
  /** Keep the name currently offered on the glass, from the phone. */
  confirmIntro: (extra?: Record<string, string>) => Promise<boolean>;
  dismissIntro: () => Promise<boolean>;
};

export const useEarStore = create<EarState>((set, get) => ({
  loaded: false,
  reachable: false,
  saving: false,
  lastError: "",
  switches: { ...EAR_SWITCH_DEFAULTS },
  runtime: { ...EAR_RUNTIME_DEFAULTS },
  intro: { pending: false, offered: 0, kept: 0 },

  refresh: async () => {
    const m = target();
    if (!m) {
      set({ loaded: true, reachable: false });
      return;
    }
    try {
      // Config is the AUTHORITY on the switches; /ear and /intro report what is
      // actually happening. Read together so a screen never draws a switch from
      // one snapshot and its status line from another.
      const [cfg, ear, intro] = await Promise.all([
        req(m, "/dreamlayer/config"),
        req(m, "/dreamlayer/ear"),
        req(m, "/dreamlayer/intro").catch(() => null),
      ]);
      const c = (cfg && cfg.config) || cfg || {};
      const e = ear || {};
      const sw: EarSwitches = { ...EAR_SWITCH_DEFAULTS };
      (Object.keys(EAR_SWITCH_DEFAULTS) as (keyof EarSwitches)[]).forEach((k) => {
        const v = c[k];
        // A key the Brain does not know is left at its default rather than
        // coerced: `undefined` becoming `false` would draw an older Brain's
        // missing feature as one the wearer had switched off.
        if (typeof v === typeof EAR_SWITCH_DEFAULTS[k]) (sw as Record<string, unknown>)[k] = v;
      });
      set({
        loaded: true,
        reachable: true,
        lastError: "",
        switches: sw,
        runtime: {
          listening: !!e.listening,
          remoteListening: !!e.remote_listening,
          heardCount: Number(e.heard_count || 0),
          canInterpret: !!e.can_interpret,
          interpretProved: !!e.interpret_proved,
          interpretedCount: Number(e.interpreted_count || 0),
          truthProved: !!e.truth_proved,
          truthReads: Number(e.truth_reads || 0),
        },
        intro: {
          pending: !!(intro && intro.pending),
          offered: Number((intro && intro.offered) || 0),
          kept: Number((intro && intro.kept) || 0),
        },
      });
    } catch {
      set({ loaded: true, reachable: false });
    }
  },

  set: async (key, value) => {
    const m = target();
    // No Brain, no change. The switch stays where it is and the screen says so —
    // see the header: these settings live on the Brain, not in this app.
    if (!m) {
      set({ lastError: "not-connected" });
      return false;
    }
    set({ saving: true, lastError: "" });
    try {
      const r = await req(m, "/dreamlayer/config", {
        method: "POST",
        body: JSON.stringify({ [key]: value }),
      });
      // A 400 from the type-check arrives as a body with `error`; treat anything
      // that isn't an explicit success as a failure and re-read rather than
      // assume. The Brain is the authority on what it stored.
      if (r && r.error) {
        // Re-read FIRST, then state the reason: `refresh` clears `lastError` on
        // a good read, so setting it before would wipe the very thing the
        // screen needs to explain why the switch did not move.
        set({ saving: false });
        await get().refresh();
        set({ lastError: String(r.error) });
        return false;
      }
      set({ saving: false });
      await get().refresh();
      return get().switches[key] === value;
    } catch {
      set({ saving: false, lastError: "unreachable" });
      return false;
    }
  },

  confirmIntro: async (extra) => {
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/intro", {
        method: "POST",
        body: JSON.stringify({ action: "confirm", ...(extra || {}) }),
      });
      await get().refresh();
      return !!(r && r.ok);
    } catch {
      return false;
    }
  },

  dismissIntro: async () => {
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/intro", {
        method: "POST",
        body: JSON.stringify({ action: "dismiss" }),
      });
      await get().refresh();
      return !!(r && r.ok);
    } catch {
      return false;
    }
  },
}));
