/**
 * useBrainStore — the phone's view of the three brain switches.
 *
 * Mirrors host-python/src/dreamlayer/orchestrator/orchestrator.py:
 *   • the phone is the brain until you connect a Mac mini
 *   • cloud is its own switch (reach for the hardest, non-personal asks)
 *   • incognito forces cloud off and pauses capture for the session
 *
 * State persists across launches (AsyncStorage). When a Mac mini is paired we
 * best-effort POST switch changes to its Brain server so the phone, the panel,
 * and the glasses agree; failures are swallowed (the local UI is the source of
 * truth and re-syncs on next change).
 */
import { create } from "zustand";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { decodePairing } from "../services/pairing";
import { useConnectionStore } from "./useConnectionStore";
import { useVitalsStore } from "./useVitalsStore";
import * as demo from "../demo/fixtures";

/** The Veil is closed if the phone/session paused capture (capturePaused, which
 *  local incognito forces on synchronously) OR the glasses raised the Veil
 *  (PRIVACY_VEIL telemetry → useVitalsStore.veiled). Defense-in-depth for the
 *  relay methods below so a direct caller can't leak captured content past the
 *  Veil either (audit 2026-07-14). */
function veilClosed(capturePaused: boolean): boolean {
  return capturePaused || useVitalsStore.getState().veiled;
}

/** A Brain just paired — complete any plugin installs queued while offline.
 *  Lazy require avoids a load-order dependency between the two stores. */
function flushPendingPlugins(m: { connected: boolean; url: string; token: string }) {
  if (!m.connected || !m.url) return;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { usePluginStore } = require("./usePluginStore");
    usePluginStore.getState().flushPending({ url: m.url, token: m.token });
  } catch {
    /* plugin store unavailable — nothing to flush */
  }
}

export type BrainKind = "phone" | "mac_mini";

export type MacMini = { connected: boolean; url: string; token: string; relayUrl?: string };
export type Glasses = { connected: boolean; id: string };
export type AskResult = { text: string; tier: string; sources: string[] } | null;
export type BriefSection = { title: string; items: string[] };
export type LongBrief = {
  text: string;
  sections: BriefSection[];
  missed?: { texts: number; emails: number };
  ts: number;
};
export type CalendarEvent = { title: string; ts: number; place?: string; source?: string; calendar?: string };
export type ActivityItem = { ts: number; kind: string; text?: string; query?: string; tier?: string };
export type RewindItem = { ts: number; kind: string; text: string };
export type RewindBlock = { hour: number; label: string; count: number; items: RewindItem[] };
export type CueKind = "event" | "person" | "place";
export type SagaAchievement = {
  id: string; name: string; what: string; how: string;
  category: "milestone" | "quest" | "explore";
  unlocked: boolean; progress: number; target: number; xp: number;
};
export type SagaSnapshot = {
  xp: number; level: number; max_level: number; rank: string;
  next_rank: { level: number; title: string } | null;
  xp_to_next: number; level_floor: number; level_ceil: number;
  unlocked_count: number; total_count: number;
  achievements: SagaAchievement[];
};
export type JunoProfile = {
  name: string;
  interests: string[];
  people: string[];
  preferences: string[];
  observations: number;
};
export type WakeSource = "voice" | "tap" | "gaze" | "raise";
export type WakeFeedback = "visual" | "audio" | "haptic";
export type BrainMessage = {
  channel: string; // "imessage" | "email"
  who: string;
  from_me: boolean;
  text: string;
  subject?: string;
  ts: number;
};

type BrainState = {
  macMini: MacMini;
  glasses: Glasses;
  cloud: boolean; // the remembered preference (independent switch)
  incognito: boolean;
  capturePaused: boolean;
  notifyTexts: boolean; // texts pop up on the glasses
  notifyEmails: boolean; // emails pop up on the glasses (separate)
  summarizeEmails: boolean; // Brain shortens long emails before relaying
  focus: boolean; // turn the interruptions down (distinct from incognito)
  cues: Record<CueKind, boolean>; // which proactive cue kinds are on
  wakeSources: Record<WakeSource, boolean>; // how Juno can be woken
  wakeFeedback: Record<WakeFeedback, boolean>; // how it shows it's listening
  proactiveAlerts: boolean; // let Juno speak up: Listen! / Watch out!
  factCheck: boolean; // Veritas: fact-check the conversation as it happens
  answerAhead: boolean; // pre-answer questions the room asks you
  demoMode: boolean; // labeled sample data so the app is alive with no hardware
  onboardingSeen: boolean; // first-run tour shown once
  setOnboardingSeen: (v: boolean) => void;
  hydrated: boolean;
  outbox: Record<string, unknown>; // config patches awaiting a reachable Brain
  unsynced: () => boolean; // the UI's honest "pending sync" marker
  flushOutbox: () => void; // drain queued patches (reconnect / pair)

  // derived
  brainKind: () => BrainKind;
  effectiveCloud: () => boolean; // cloud actually in force (off while incognito)

  // switches
  connectMacMini: (on: boolean) => void;
  setCloud: (on: boolean) => void;
  setIncognito: (on: boolean) => void;
  setCapturePaused: (on: boolean) => void;
  setNotifyTexts: (on: boolean) => void;
  setNotifyEmails: (on: boolean) => void;
  setSummarizeEmails: (on: boolean) => void;
  connectGlasses: (id: string) => void;
  disconnectGlasses: () => void;

  // Demo Mode — populate every screen with labeled sample data (no network),
  // so the app is fully explorable with no glasses and no Mac Brain paired.
  enableDemo: () => void;
  disableDemo: () => void;

  // pairing + recall
  pairFromCode: (code: string) => { brain: boolean; glasses: boolean };
  ask: (query: string) => Promise<AskResult>;
  // the deliberate camera tier: a phone photo through the Brain's vision path
  explain: (imageB64: string, label?: string) => Promise<AskResult>;

  // the lens relay — closes the glass→Brain→glass loop for the live showcases:
  //  • feedLens streams host text (a translation, a camera label, a memory)
  //    into the running lens's {slot}
  //  • emitLens forwards a lens's emit tag; "ask" runs the Brain over the
  //    spoken question and the answer lands back on the glass
  feedLens: (text: string, source?: string) => Promise<boolean>;
  emitLens: (tag: string, text?: string) => Promise<AskResult>;

  // one-glance morning brief synthesized by the Brain
  getBrief: (agenda?: string[]) => Promise<{ text: string; missed?: { texts: number; emails: number } } | null>;
  // the brief the Brain's scheduler delivered on its own at brief_hour (no compute)
  getLatestBrief: () => Promise<{ text: string; bullets: string[]; ts: number } | null>;
  // the extended "long brief" — sectioned; fetched on demand and kept on the phone
  getLongBrief: (opts?: { agenda?: string[]; commitments?: string[]; memories?: string[] })
    => Promise<LongBrief | null>;
  longBrief: LongBrief | null;                 // last one, persisted on the phone

  // engines surfaced in the app
  proactiveCards: boolean;
  setProactiveCards: (on: boolean) => void;
  setFocus: (on: boolean) => void;
  setCue: (kind: CueKind, on: boolean) => void;
  setWakeSource: (source: WakeSource, on: boolean) => void;
  setWakeFeedback: (kind: WakeFeedback, on: boolean) => void;
  setProactiveAlerts: (on: boolean) => void;
  setFactCheck: (on: boolean) => void;
  setAnswerAhead: (on: boolean) => void;
  sendVoice: (text: string) => Promise<{ intent: string; answer?: string; say?: string; text?: string; to?: string; subject?: string }>;
  getCalendar: () => Promise<CalendarEvent[]>;
  addEvent: (e: { title: string; ts: number; place?: string }) => Promise<CalendarEvent[]>;
  removeEvent: (e: { title: string; ts: number }) => Promise<CalendarEvent[]>;
  syncCalendar: () => Promise<CalendarEvent[]>;
  getActivity: () => Promise<ActivityItem[]>;
  getRewind: () => Promise<RewindBlock[]>;
  getSaga: () => Promise<SagaSnapshot | null>;
  recordSaga: (event: string) => Promise<void>;
  getProfile: () => Promise<JunoProfile | null>;

  // messages relayed by the Brain — read on the glasses, reply hands-free
  fetchMessages: () => Promise<{ items: BrainMessage[]; enabled: boolean }>;
  sendReply: (m: { channel: string; to: string; subject?: string; text: string }) => Promise<{ ok: boolean; error?: string }>;
  getReplies: (text: string) => Promise<string[]>;

  hydrate: () => Promise<void>;
};

const KEY = "dreamlayer.brain.v1";

function persist(s: BrainState) {
  const snap = {
    macMini: s.macMini,
    glasses: s.glasses,
    cloud: s.cloud,
    incognito: s.incognito,
    capturePaused: s.capturePaused,
    notifyTexts: s.notifyTexts,
    notifyEmails: s.notifyEmails,
    summarizeEmails: s.summarizeEmails,
    proactiveCards: s.proactiveCards,
    focus: s.focus,
    cues: s.cues,
    wakeSources: s.wakeSources,
    wakeFeedback: s.wakeFeedback,
    proactiveAlerts: s.proactiveAlerts,
    factCheck: s.factCheck,
    answerAhead: s.answerAhead,
    demoMode: s.demoMode,
    onboardingSeen: s.onboardingSeen,
    longBrief: s.longBrief,
    outbox: s.outbox,
  };
  AsyncStorage.setItem(KEY, JSON.stringify(snap)).catch(() => {});
}

function headers(m: MacMini): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (m.token) h["X-DreamLayer-Token"] = m.token;
  return h;
}

/**
 * Reach the Brain, preferring your home LAN and falling back to the relay
 * (reach-anywhere) when the LAN address can't be reached — so recall and
 * messages keep working when you're out. The relay *server* is infra you host;
 * this is the client that uses it.
 *
 * Every outcome is reported to useConnectionStore, so the app has ONE truth
 * about reachability instead of a guess per call.
 */
async function brainFetch(m: MacMini, path: string, opts: RequestInit = {}): Promise<Response> {
  const conn = useConnectionStore.getState();
  const o: RequestInit = { ...opts, headers: { ...headers(m), ...(opts.headers as object) } };
  try {
    const r = await fetch(m.url + path, o);
    conn.noteLan();
    return r;
  } catch (e) {
    if (m.relayUrl) {
      try {
        const r = await fetch(m.relayUrl + path, o);
        conn.noteRelay();
        return r;
      } catch (e2) {
        conn.noteFailure();
        throw e2;
      }
    }
    conn.noteFailure();
    throw e;
  }
}

/**
 * The config outbox: switch changes the Brain must learn about are pushed
 * through here. A failed push is not swallowed anymore — the patch is kept
 * (merged, persisted) and drained the moment the connection store reports
 * the Brain back, so a toggle flipped in a tunnel still lands. The UI can
 * read `unsynced` and mark the pending state honestly.
 */
function pushConfig(get: () => BrainState, set: (p: Partial<BrainState>) => void,
                    patch: Record<string, unknown>) {
  const s = get();
  const m = s.macMini;
  const merged = { ...s.outbox, ...patch };
  if (!m.connected || !m.url) {
    set({ outbox: merged });
    persist(get());
    return;
  }
  brainFetch(m, "/dreamlayer/config", {
    method: "POST",
    body: JSON.stringify(merged),
  })
    .then(() => {
      set({ outbox: {} });
      persist(get());
    })
    .catch(() => {
      set({ outbox: merged });
      persist(get());
    });
}

// the switches the Brain mirrors, derived from current state
function switchPatch(s: BrainState): Record<string, unknown> {
  return {
    cloud_enabled: s.effectiveCloud(),
    network_mode: s.incognito ? "lan_only" : "connected",
  };
}

export const useBrainStore = create<BrainState>((set, get) => ({
  macMini: { connected: false, url: "", token: "", relayUrl: "" },
  glasses: { connected: false, id: "" },
  cloud: false,
  incognito: false,
  capturePaused: false,
  notifyTexts: true,
  notifyEmails: true,
  summarizeEmails: false,
  proactiveCards: true,
  focus: false,
  cues: { event: true, person: true, place: true },
  wakeSources: { voice: true, tap: true, gaze: true, raise: true },
  wakeFeedback: { visual: true, audio: true, haptic: true },
  proactiveAlerts: true,
  factCheck: false,
  answerAhead: false,
  demoMode: false,
  onboardingSeen: false,
  longBrief: null,
  hydrated: false,
  outbox: {},

  brainKind: () => (get().macMini.connected ? "mac_mini" : "phone"),
  effectiveCloud: () => (get().incognito ? false : get().cloud),
  unsynced: () => Object.keys(get().outbox).length > 0,

  flushOutbox: () => {
    const s = get();
    if (Object.keys(s.outbox).length === 0) return;
    pushConfig(get, set, {});          // pushes the merged outbox as-is
  },

  connectMacMini: (on) => {
    set((s) => ({ macMini: { ...s.macMini, connected: on } }));
    const s = get();
    persist(s);
    if (on) {
      pushConfig(get, set, switchPatch(s));
      flushPendingPlugins(s.macMini);
    }
  },

  setCloud: (on) => {
    set({ cloud: on });
    persist(get());
    pushConfig(get, set, switchPatch(get()));
  },

  setIncognito: (on) => {
    set({ incognito: on, capturePaused: on ? true : get().capturePaused });
    persist(get());
    pushConfig(get, set, switchPatch(get()));
  },

  setCapturePaused: (on) => {
    set({ capturePaused: on });
    persist(get());
  },

  setNotifyTexts: (on) => {
    set({ notifyTexts: on });
    persist(get());
  },

  setNotifyEmails: (on) => {
    set({ notifyEmails: on });
    persist(get());
  },

  setSummarizeEmails: (on) => {
    set({ summarizeEmails: on });
    persist(get());
    // this one lives on the Brain (it has the model) — outboxed like the rest
    pushConfig(get, set, { summarize_emails: on });
  },

  connectGlasses: (id) => {
    set({ glasses: { connected: true, id } });
    persist(get());
  },

  disconnectGlasses: () => {
    set({ glasses: { connected: false, id: "" } });
    persist(get());
  },

  enableDemo: () => {
    // mark a demo Halo paired (no network) so device-gated screens light up;
    // the store getters below serve fixtures whenever demoMode is on, and the
    // memory store gets its demo seed (lazy require: no load-order dependency).
    set((s) => ({ demoMode: true, glasses: { connected: true, id: s.glasses.id || "HALO-DEMO" } }));
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      require("./useMemoryStore").seedDemoMemories();
    } catch { /* memory store unavailable — nothing to seed */ }
    persist(get());
  },

  disableDemo: () => {
    // demo-off must LEAVE no fiction behind: unpair the demo Halo and strip
    // the seeded demo memories/card (real ingested/fetched entries survive).
    set((s) => ({
      demoMode: false,
      glasses: s.glasses.id === "HALO-DEMO" ? { connected: false, id: "" } : s.glasses,
    }));
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      require("./useMemoryStore").clearDemoMemories();
    } catch { /* memory store unavailable — nothing to clear */ }
    persist(get());
  },

  setOnboardingSeen: (v) => {
    set({ onboardingSeen: v });
    persist(get());
  },

  pairFromCode: (code) => {
    const b = decodePairing(code);
    if (b.brainUrl) {
      set({ macMini: { connected: true, url: b.brainUrl, token: b.token, relayUrl: b.relayUrl } });
    }
    if (b.glassesId) {
      set({ glasses: { connected: true, id: b.glassesId } });
    }
    const s = get();
    persist(s);
    if (b.brainUrl) {
      pushConfig(get, set, switchPatch(s));   // drains the outbox too
      flushPendingPlugins(s.macMini);
    }
    return { brain: !!b.brainUrl, glasses: !!b.glassesId };
  },

  ask: async (query) => {
    if (get().demoMode) return demo.demoAsk(query);
    const m = get().macMini;
    if (!m.connected || !m.url) {
      return {
        text: "Connect your Mac mini to search your own files and mail. The phone alone answers from DreamLayer's memory only.",
        tier: "device",
        sources: [],
      };
    }
    try {
      const r = await brainFetch(m, "/dreamlayer/brain/ask", {
        method: "POST",
        // carry the wearer's session posture: incognito (or Cloud off) means the
        // paired Brain must NOT escalate this ask to its own cloud. effectiveCloud
        // is false while incognito, so no_cloud follows both switches.
        body: JSON.stringify({ query, no_cloud: !get().effectiveCloud() }),
      });
      const j = await r.json();
      return { text: j.text ?? "", tier: j.tier ?? "", sources: j.sources ?? [] };
    } catch {
      return { text: "Couldn't reach your Brain. Is the Mac mini awake and reachable (LAN or relay)?", tier: "", sources: [] };
    }
  },

  explain: async (imageB64, label = "") => {
    // The deliberate camera tier: pulling out the phone IS consent and
    // intent, the sensor is 10x the Halo snapshot, and there's no BLE tax.
    // Same pipeline the glasses use — POST /dreamlayer/brain/explain.
    if (get().demoMode) {
      return {
        text: "Snake plant — water every 2–3 weeks; yours looks thirsty. (demo)",
        tier: "device",
        sources: ["demo"],
      };
    }
    const m = get().macMini;
    if (!m.connected || !m.url) {
      return { text: "Pair your Brain to explain what you see.", tier: "", sources: [] };
    }
    try {
      const r = await brainFetch(m, "/dreamlayer/brain/explain", {
        method: "POST",
        body: JSON.stringify({ label, image: imageB64, want: "rich" }),
      });
      const j = await r.json();
      return { text: j.text ?? "", tier: j.tier ?? "", sources: j.sources ?? [] };
    } catch {
      return { text: "Couldn't reach your Brain — try again when it's back.", tier: "", sources: [] };
    }
  },

  // -- the lens relay: close the loop on the phone side ----------------------
  feedLens: async (text, source = "") => {
    if (get().demoMode) return true;                 // the builder sim already shows it
    // host capture (translation / camera label / memory) — never stream it into
    // the lens while the Veil is closed from either end.
    if (veilClosed(get().capturePaused)) return false;
    const m = get().macMini;
    if (!m.connected || !m.url || !text) return false;
    try {
      const r = await brainFetch(m, "/dreamlayer/rc/feed", {
        method: "POST",
        body: JSON.stringify({ text, source }),
      });
      const j = await r.json();
      return !!j.ok;
    } catch {
      return false;
    }
  },

  emitLens: async (tag, text = "") => {
    if (get().demoMode) return { text: "", tier: "device", sources: [] };
    // only "ask" carries captured speech; refuse it while the Veil is closed.
    // Other tags are inert lens control signals with no captured payload.
    if (tag === "ask" && veilClosed(get().capturePaused)) return null;
    const m = get().macMini;
    if (!m.connected || !m.url || !tag) return null;
    try {
      const r = await brainFetch(m, "/dreamlayer/rc/emit", {
        method: "POST",
        // a lens "ask" emit reaches the same cloud sink — carry the posture too
        body: JSON.stringify({ tag, text, no_cloud: !get().effectiveCloud() }),
      });
      const j = await r.json();
      // "ask" comes back with the Brain's answer (already pushed to the glass)
      return { text: j.answer ?? j.text ?? "", tier: j.tier ?? "", sources: [] };
    } catch {
      return null;
    }
  },

  setProactiveCards: (on) => {
    set({ proactiveCards: on });
    persist(get());
  },

  setFocus: (on) => {
    set({ focus: on });
    persist(get());
    if (on) get().recordSaga("focus"); // unlock the Deep Focus badge
  },

  setCue: (kind, on) => {
    set({ cues: { ...get().cues, [kind]: on } });
    persist(get());
  },

  setWakeSource: (source, on) => {
    set({ wakeSources: { ...get().wakeSources, [source]: on } });
    persist(get());
  },

  setWakeFeedback: (kind, on) => {
    set({ wakeFeedback: { ...get().wakeFeedback, [kind]: on } });
    persist(get());
  },

  setProactiveAlerts: (on) => {
    set({ proactiveAlerts: on });
    persist(get());
  },

  setFactCheck: (on) => {
    set({ factCheck: on });
    persist(get());
  },

  setAnswerAhead: (on) => {
    set({ answerAhead: on });
    persist(get());
  },

  sendVoice: async (text) => {
    if (get().demoMode) return demo.demoVoice(text);
    const m = get().macMini;
    if (!m.connected || !m.url) return { intent: "ask", answer: "" };
    try {
      const r = await brainFetch(m, "/dreamlayer/voice", { method: "POST", body: JSON.stringify({ text, no_cloud: !get().effectiveCloud() }) });
      return await r.json();
    } catch {
      return { intent: "ask", answer: "Couldn't reach your Brain." };
    }
  },

  getCalendar: async () => {
    if (get().demoMode) return demo.demoCalendar;
    const m = get().macMini;
    if (!m.connected || !m.url) return [];
    try {
      const r = await brainFetch(m, "/dreamlayer/calendar");
      return (await r.json()).items ?? [];
    } catch {
      return [];
    }
  },

  addEvent: async (e) => {
    if (get().demoMode) return demo.demoCalendar;
    const m = get().macMini;
    if (!m.connected || !m.url) return [];
    try {
      const r = await brainFetch(m, "/dreamlayer/calendar", { method: "POST", body: JSON.stringify(e) });
      return (await r.json()).items ?? [];
    } catch {
      return [];
    }
  },

  removeEvent: async (e) => {
    if (get().demoMode) return demo.demoCalendar;
    const m = get().macMini;
    if (!m.connected || !m.url) return [];
    try {
      const r = await brainFetch(m, "/dreamlayer/calendar", {
        method: "POST",
        body: JSON.stringify({ remove: true, title: e.title, ts: e.ts }),
      });
      return (await r.json()).items ?? [];
    } catch {
      return [];
    }
  },

  syncCalendar: async () => {
    if (get().demoMode) return demo.demoCalendar;
    const m = get().macMini;
    if (!m.connected || !m.url) return [];
    try {
      const r = await brainFetch(m, "/dreamlayer/calendar/sync", { method: "POST", body: "{}" });
      return (await r.json()).items ?? [];
    } catch {
      return [];
    }
  },

  getRewind: async () => {
    if (get().demoMode) return demo.demoRewind;
    const m = get().macMini;
    if (!m.connected || !m.url) return [];
    try {
      const r = await brainFetch(m, "/dreamlayer/rewind");
      return (await r.json()).blocks ?? [];
    } catch {
      return [];
    }
  },

  getSaga: async () => {
    if (get().demoMode) return demo.demoSaga;
    const m = get().macMini;
    if (!m.connected || !m.url) return null;
    try {
      const r = await brainFetch(m, "/dreamlayer/saga");
      return (await r.json()) as SagaSnapshot;
    } catch {
      return null;
    }
  },

  recordSaga: async (event) => {
    const m = get().macMini;
    if (!m.connected || !m.url) return;
    try {
      await brainFetch(m, "/dreamlayer/saga/record", {
        method: "POST",
        body: JSON.stringify({ event }),
      });
    } catch {
      /* best-effort — a badge is not worth an error */
    }
  },

  getProfile: async () => {
    if (get().demoMode) return demo.demoProfile;
    const m = get().macMini;
    if (!m.connected || !m.url) return null;
    try {
      const r = await brainFetch(m, "/dreamlayer/profile");
      return (await r.json()) as JunoProfile;
    } catch {
      return null;
    }
  },

  getActivity: async () => {
    if (get().demoMode) return demo.demoActivity;
    const m = get().macMini;
    if (!m.connected || !m.url) return [];
    try {
      const r = await brainFetch(m, "/dreamlayer/history");
      return (await r.json()).items ?? [];
    } catch {
      return [];
    }
  },

  getBrief: async (agenda = []) => {
    if (get().demoMode) return demo.demoBrief;
    const m = get().macMini;
    if (!m.connected || !m.url) return null;
    try {
      const r = await fetch(m.url + "/dreamlayer/brief", {
        method: "POST",
        headers: headers(m),
        body: JSON.stringify({ agenda }),
      });
      const j = await r.json();
      return { text: j.text ?? "", missed: j.missed };
    } catch {
      return null;
    }
  },

  getLatestBrief: async () => {
    if (get().demoMode) return { text: demo.demoBrief.text, bullets: demo.demoLongBrief.sections.flatMap((x) => x.items).slice(0, 4), ts: 1 };
    const m = get().macMini;
    if (!m.connected || !m.url) return null;
    try {
      const r = await brainFetch(m, "/dreamlayer/brief/latest");
      const j = await r.json();
      if (!j || !j.ts) return null;
      return { text: j.text ?? "", bullets: j.bullets ?? [], ts: j.ts };
    } catch {
      return null;
    }
  },

  getLongBrief: async (opts = {}) => {
    if (get().demoMode) {
      set({ longBrief: demo.demoLongBrief });
      persist(get());
      return demo.demoLongBrief;
    }
    const m = get().macMini;
    if (!m.connected || !m.url) return null;
    try {
      const r = await brainFetch(m, "/dreamlayer/brief", {
        method: "POST",
        body: JSON.stringify({
          depth: "long",
          agenda: opts.agenda ?? [],
          commitments: opts.commitments ?? [],
          memories: opts.memories ?? [],
        }),
      });
      const j = await r.json();
      const brief: LongBrief = {
        text: j.text ?? "",
        sections: j.sections ?? [],
        missed: j.missed,
        ts: Date.now(),
      };
      const s = { ...get(), longBrief: brief };
      set({ longBrief: brief });
      persist(s);
      return brief;
    } catch {
      return null;
    }
  },

  fetchMessages: async () => {
    if (get().demoMode) return demo.demoMessages;
    const m = get().macMini;
    if (!m.connected || !m.url) return { items: [], enabled: false };
    try {
      const r = await brainFetch(m, "/dreamlayer/messages/recent");
      const j = await r.json();
      return { items: j.items ?? [], enabled: !!j.enabled };
    } catch {
      return { items: [], enabled: false };
    }
  },

  sendReply: async (draft) => {
    if (get().demoMode) return { ok: true };
    const m = get().macMini;
    if (!m.connected || !m.url) return { ok: false, error: "No Brain paired" };
    try {
      const r = await fetch(m.url + "/dreamlayer/message/send", {
        method: "POST",
        headers: headers(m),
        body: JSON.stringify({ ...draft, approved: true }),
      });
      const j = await r.json();
      return j.error ? { ok: false, error: j.error } : { ok: true };
    } catch {
      return { ok: false, error: "Couldn't reach your Brain" };
    }
  },

  getReplies: async (text) => {
    if (get().demoMode) return demo.demoReplies(text);
    const m = get().macMini;
    if (!m.connected || !m.url) return [];
    try {
      const r = await fetch(m.url + "/dreamlayer/replies", {
        method: "POST",
        headers: headers(m),
        body: JSON.stringify({ text }),
      });
      const j = await r.json();
      return j.replies ?? [];
    } catch {
      return [];
    }
  },

  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(KEY);
      if (raw) {
        const snap = JSON.parse(raw);
        set({ ...snap, hydrated: true });
        // settle the connection pill (and drain any outbox) right away
        const m = get().macMini;
        if (m.connected && m.url) {
          useConnectionStore.getState().probe(m).catch(() => {});
        } else {
          useConnectionStore.getState().noteUnpaired();
        }
        return;
      }
    } catch {
      /* fall through to defaults */
    }
    set({ hydrated: true });
  },
}));

// The Brain coming back is the moment queued config lands — one listener,
// registered once at module scope.
useConnectionStore.getState().onReconnect(() => {
  try {
    useBrainStore.getState().flushOutbox();
  } catch {
    /* never let a drain error break the connection machine */
  }
});
