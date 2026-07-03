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

export type BrainKind = "phone" | "mac_mini";

export type MacMini = { connected: boolean; url: string; token: string; relayUrl?: string };
export type Glasses = { connected: boolean; id: string };
export type AskResult = { text: string; tier: string; sources: string[] } | null;
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
  wakeSources: Record<WakeSource, boolean>; // how Oracle can be woken
  wakeFeedback: Record<WakeFeedback, boolean>; // how it shows it's listening
  proactiveAlerts: boolean; // let Oracle speak up: Listen! / Watch out!
  factCheck: boolean; // Veritas: fact-check the conversation as it happens
  answerAhead: boolean; // pre-answer questions the room asks you
  hydrated: boolean;

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

  // pairing + recall
  pairFromCode: (code: string) => { brain: boolean; glasses: boolean };
  ask: (query: string) => Promise<AskResult>;

  // one-glance morning brief synthesized by the Brain
  getBrief: (agenda?: string[]) => Promise<{ text: string; missed?: { texts: number; emails: number } } | null>;
  // the brief the Brain's scheduler delivered on its own at brief_hour (no compute)
  getLatestBrief: () => Promise<{ text: string; bullets: string[]; ts: number } | null>;

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
  sendVoice: (text: string) => Promise<{ intent: string; answer?: string; text?: string; to?: string; subject?: string }>;
  getCalendar: () => Promise<CalendarEvent[]>;
  addEvent: (e: { title: string; ts: number; place?: string }) => Promise<CalendarEvent[]>;
  removeEvent: (e: { title: string; ts: number }) => Promise<CalendarEvent[]>;
  syncCalendar: () => Promise<CalendarEvent[]>;
  getActivity: () => Promise<ActivityItem[]>;
  getRewind: () => Promise<RewindBlock[]>;
  getSaga: () => Promise<SagaSnapshot | null>;
  recordSaga: (event: string) => Promise<void>;

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
 */
async function brainFetch(m: MacMini, path: string, opts: RequestInit = {}): Promise<Response> {
  const o: RequestInit = { ...opts, headers: { ...headers(m), ...(opts.headers as object) } };
  try {
    return await fetch(m.url + path, o);
  } catch (e) {
    if (m.relayUrl) return await fetch(m.relayUrl + path, o);
    throw e;
  }
}

// best-effort push of the current switches to the paired Brain
function syncToBrain(s: BrainState) {
  const m = s.macMini;
  if (!m.connected || !m.url) return;
  fetch(m.url + "/dreamlayer/config", {
    method: "POST",
    headers: headers(m),
    body: JSON.stringify({
      cloud_enabled: s.effectiveCloud(),
      network_mode: s.incognito ? "lan_only" : "connected",
    }),
  }).catch(() => {});
}

export const useBrainStore = create<BrainState>((set, get) => ({
  macMini: { connected: false, url: "", token: "", relayUrl: "" },
  glasses: { connected: false, id: "" },
  cloud: true,
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
  hydrated: false,

  brainKind: () => (get().macMini.connected ? "mac_mini" : "phone"),
  effectiveCloud: () => (get().incognito ? false : get().cloud),

  connectMacMini: (on) => {
    set((s) => ({ macMini: { ...s.macMini, connected: on } }));
    const s = get();
    persist(s);
    syncToBrain(s);
  },

  setCloud: (on) => {
    set({ cloud: on });
    const s = get();
    persist(s);
    syncToBrain(s);
  },

  setIncognito: (on) => {
    set({ incognito: on, capturePaused: on ? true : get().capturePaused });
    const s = get();
    persist(s);
    syncToBrain(s);
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
    const s = get();
    persist(s);
    // this one lives on the Brain (it has the model) — push it there
    const m = s.macMini;
    if (m.connected && m.url) {
      fetch(m.url + "/dreamlayer/config", {
        method: "POST",
        headers: headers(m),
        body: JSON.stringify({ summarize_emails: on }),
      }).catch(() => {});
    }
  },

  connectGlasses: (id) => {
    set({ glasses: { connected: true, id } });
    persist(get());
  },

  disconnectGlasses: () => {
    set({ glasses: { connected: false, id: "" } });
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
    syncToBrain(s);
    return { brain: !!b.brainUrl, glasses: !!b.glassesId };
  },

  ask: async (query) => {
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
        body: JSON.stringify({ query }),
      });
      const j = await r.json();
      return { text: j.text ?? "", tier: j.tier ?? "", sources: j.sources ?? [] };
    } catch {
      return { text: "Couldn't reach your Brain. Is the Mac mini awake and reachable (LAN or relay)?", tier: "", sources: [] };
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
    const m = get().macMini;
    if (!m.connected || !m.url) return { intent: "ask", answer: "" };
    try {
      const r = await brainFetch(m, "/dreamlayer/voice", { method: "POST", body: JSON.stringify({ text }) });
      return await r.json();
    } catch {
      return { intent: "ask", answer: "Couldn't reach your Brain." };
    }
  },

  getCalendar: async () => {
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

  getActivity: async () => {
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

  fetchMessages: async () => {
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
        return;
      }
    } catch {
      /* fall through to defaults */
    }
    set({ hydrated: true });
  },
}));
