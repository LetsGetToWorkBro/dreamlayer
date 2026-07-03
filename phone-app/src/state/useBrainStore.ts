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

export type MacMini = { connected: boolean; url: string; token: string };
export type Glasses = { connected: boolean; id: string };
export type AskResult = { text: string; tier: string; sources: string[] } | null;
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

  // messages relayed by the Brain — read on the glasses, reply hands-free
  fetchMessages: () => Promise<{ items: BrainMessage[]; enabled: boolean }>;
  sendReply: (m: { channel: string; to: string; subject?: string; text: string }) => Promise<{ ok: boolean; error?: string }>;

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
  };
  AsyncStorage.setItem(KEY, JSON.stringify(snap)).catch(() => {});
}

function headers(m: MacMini): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (m.token) h["X-DreamLayer-Token"] = m.token;
  return h;
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
  macMini: { connected: false, url: "", token: "" },
  glasses: { connected: false, id: "" },
  cloud: true,
  incognito: false,
  capturePaused: false,
  notifyTexts: true,
  notifyEmails: true,
  summarizeEmails: false,
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
      set({ macMini: { connected: true, url: b.brainUrl, token: b.token } });
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
      const r = await fetch(m.url + "/dreamlayer/brain/ask", {
        method: "POST",
        headers: headers(m),
        body: JSON.stringify({ query }),
      });
      const j = await r.json();
      return { text: j.text ?? "", tier: j.tier ?? "", sources: j.sources ?? [] };
    } catch {
      return { text: "Couldn't reach your Brain. Is the Mac mini awake and on the same network?", tier: "", sources: [] };
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

  fetchMessages: async () => {
    const m = get().macMini;
    if (!m.connected || !m.url) return { items: [], enabled: false };
    try {
      const r = await fetch(m.url + "/dreamlayer/messages/recent", { headers: headers(m) });
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
