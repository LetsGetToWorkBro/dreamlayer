/**
 * useMemoryStore — the phone's window onto DreamLayer's own memory.
 *
 * The real memories live on the brain (phone on-device store, or the Mac mini
 * when connected). This store mirrors the most recent ones for the Memories
 * tab and exposes `service.lastCard` — the last card the glasses drew — plus
 * `purgeAll()` for the danger zone. It ships with a few sample memories so the
 * surface is alive before a Halo has ever been worn; `purgeAll()` clears them.
 */
import { create } from "zustand";

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
  service: {
    lastCard: HaloCard;
    purgeAll: () => void;
    setLastCard: (c: HaloCard) => void;
  };
  refresh: () => void;
  ingest: (m: Memory) => void;
};

const HOUR = 3_600_000;
const now = Date.now();

const SEED: Memory[] = [
  { id: "m1", kind: "Promise", summary: "Send Marcus the signed lease by Friday", createdAt: "9:42 AM", ts: now - 2 * HOUR },
  { id: "m2", kind: "Object", summary: "Snake plant on the sill — water every 2 weeks", createdAt: "9:10 AM", ts: now - 3 * HOUR },
  { id: "m3", kind: "Person", summary: "Priya — you met at the Overpass show, she teaches ceramics", createdAt: "Yesterday, 7:20 PM", ts: now - 26 * HOUR },
  { id: "m4", kind: "Place", summary: "Left the bike locked on 4th & Alder, north rack", createdAt: "Yesterday, 5:03 PM", ts: now - 28 * HOUR },
  { id: "m5", kind: "Note", summary: "Café on Pine takes cash only — bring some next time", createdAt: "Mon, 1:15 PM", ts: now - 74 * HOUR },
];

export const useMemoryStore = create<MemoryState>((set, get) => ({
  memories: SEED,
  service: {
    lastCard: { kind: "Promise", primary: "You owe Marcus the signed lease", lines: ["due Friday", "tap to open the thread"] },
    purgeAll: () => set({ memories: [] }),
    setLastCard: (c) => set((s) => ({ service: { ...s.service, lastCard: c } })),
  },
  refresh: () => {
    /* on a real device this pulls from the brain; local-first keeps state */
  },
  ingest: (m) => set((s) => ({ memories: [m, ...s.memories] })),
}));
