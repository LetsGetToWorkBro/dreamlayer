/**
 * useMemoryStore — the phone's window onto DreamLayer's own memory.
 *
 * The real memories live on the brain (phone on-device store, or the Mac mini
 * when connected). `refresh()` pulls the paired Brain's kept memory —
 * GET /dreamlayer/memories: places you saved (Waypath), people you've met and
 * favors owed (Social Lens), and dated reminders — and replaces the list.
 * Exposes `service.lastCard` (the last card the glasses drew) and `purgeAll()`
 * for the danger zone. Sample memories exist but belong to DEMO MODE only:
 * enableDemo() seeds them, disableDemo() removes them (real entries survive),
 * and a fresh real-mode install starts honestly empty.
 */
import { create } from "zustand";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useBrainStore } from "./useBrainStore";

// Offline read-cache: the last successful fetch, with a staleness stamp.
// "Offline-first" has to be true where the user actually feels it — an
// unreachable Brain shows what you knew (and WHEN you knew it), not
// fixtures or an empty screen.
const CACHE_KEY = "dreamlayer.memories.cache.v1";

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

function normalizeMemory(x: any, i: number): Memory {
  return {
    id: String(x?.id ?? `m${i}`),
    kind: String(x?.kind ?? "Note"),
    summary: String(x?.summary ?? ""),
    createdAt: String(x?.createdAt ?? ""),
    ts: Number(x?.ts ?? 0) || 0,
  };
}

export type Memory = {
  id: string;
  kind: string; // "Object" | "Person" | "Promise" | "Place" | "Note"
  summary: string;
  createdAt: string; // human label, e.g. "9:42 AM"
  ts: number; // epoch ms, for grouping by day
};

export type HaloCard = {
  kind: string;
  primary: string;
  lines?: string[];
} | null;

type MemoryState = {
  memories: Memory[];
  fetchedAt: number; // epoch ms of the last successful Brain fetch (0 = never)
  service: {
    lastCard: HaloCard;
    purgeAll: () => void;
    setLastCard: (c: HaloCard) => void;
  };
  refresh: () => Promise<void>;
  ingest: (m: Memory) => void;
  hydrateCache: () => Promise<void>;
};

const HOUR = 3_600_000;
const now = Date.now();

// Demo-mode fixtures ONLY (P2-14). These are fiction — Marcus, Priya, and the
// bike on 4th & Alder do not exist — so they may appear exactly when the app
// says "demo" and never otherwise. They are seeded by enableDemo(), removed by
// disableDemo() (by these ids, so real ingested/fetched memories survive), and
// are absent from a fresh real-mode install: an empty memory list is the
// honest state before a Halo has captured anything.
const DEMO_ID_PREFIX = "demo-";
const DEMO_SEED: Memory[] = [
  { id: "demo-m1", kind: "Promise", summary: "Send Marcus the signed lease by Friday", createdAt: "9:42 AM", ts: now - 2 * HOUR },
  { id: "demo-m2", kind: "Object", summary: "Snake plant on the sill — water every 2 weeks", createdAt: "9:10 AM", ts: now - 3 * HOUR },
  { id: "demo-m3", kind: "Person", summary: "Priya — you met at the Overpass show, she teaches ceramics", createdAt: "Yesterday, 7:20 PM", ts: now - 26 * HOUR },
  { id: "demo-m4", kind: "Place", summary: "Left the bike locked on 4th & Alder, north rack", createdAt: "Yesterday, 5:03 PM", ts: now - 28 * HOUR },
  { id: "demo-m5", kind: "Note", summary: "Café on Pine takes cash only — bring some next time", createdAt: "Mon, 1:15 PM", ts: now - 74 * HOUR },
];
const DEMO_LAST_CARD: HaloCard = {
  kind: "Promise", primary: "You owe Marcus the signed lease",
  lines: ["due Friday", "tap to open the thread"],
};

/** Seed the demo fixtures (called by useBrainStore.enableDemo). Idempotent. */
export function seedDemoMemories(): void {
  useMemoryStore.setState((s) => ({
    memories: [
      ...DEMO_SEED.filter((d) => !s.memories.some((m) => m.id === d.id)),
      ...s.memories,
    ],
    service: { ...s.service, lastCard: s.service.lastCard ?? DEMO_LAST_CARD },
  }));
}

/** Remove ONLY the demo fixtures (called by useBrainStore.disableDemo):
 * real ingested/fetched memories survive demo-off untouched. */
export function clearDemoMemories(): void {
  useMemoryStore.setState((s) => ({
    memories: s.memories.filter((m) => !m.id.startsWith(DEMO_ID_PREFIX)),
    service: {
      ...s.service,
      lastCard: s.service.lastCard === DEMO_LAST_CARD ? null : s.service.lastCard,
    },
  }));
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  memories: [],
  fetchedAt: 0,
  service: {
    lastCard: null,
    purgeAll: () => {
      // "This cannot be undone." Honor it in all three places the memories
      // live: in-memory state, the Brain's kept anchors, AND the on-disk
      // cache — otherwise hydrateCache() resurrects the erased list on the
      // next launch and the promise is a lie.
      set({ memories: [], fetchedAt: 0 });
      AsyncStorage.removeItem(CACHE_KEY).catch(() => {});
      const m = target();
      if (m) req(m, "/dreamlayer/memories/purge", { method: "POST", body: "{}" }).catch(() => {});
    },
    setLastCard: (c) => set((s) => ({ service: { ...s.service, lastCard: c } })),
  },
  refresh: async () => {
    // Pull the paired Brain's kept memory. With no Brain, keep whatever's local
    // (ingested entries, the offline cache, or demo fixtures) so the surface
    // stays alive offline.
    const m = target();
    if (!m) return;
    try {
      const r = await req(m, "/dreamlayer/memories");
      // only a well-formed answer replaces the list — an error body (e.g. a
      // stale token's {"error":"unauthorised"}) must not wipe local memories
      if (Array.isArray(r?.memories)) {
        const memories = r.memories.map(normalizeMemory);
        const fetchedAt = Date.now();
        set({ memories, fetchedAt });
        AsyncStorage.setItem(CACHE_KEY,
          JSON.stringify({ memories, fetchedAt })).catch(() => {});
      }
    } catch {
      /* unreachable → keep current (the cache, or what's been ingested) */
    }
  },
  ingest: (m) => set((s) => ({ memories: [m, ...s.memories] })),
  hydrateCache: async () => {
    try {
      const raw = await AsyncStorage.getItem(CACHE_KEY);
      if (!raw) return;
      const snap = JSON.parse(raw);
      if (Array.isArray(snap?.memories) && snap.memories.length) {
        set({ memories: snap.memories.map(normalizeMemory),
              fetchedAt: Number(snap.fetchedAt) || 0 });
      }
    } catch {
      /* a corrupt cache never blocks boot */
    }
  },
}));
