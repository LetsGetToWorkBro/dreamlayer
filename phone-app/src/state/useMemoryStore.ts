/**
 * useMemoryStore — the phone's window onto DreamLayer's own memory.
 *
 * The real memories live on the brain (phone on-device store, or the Mac mini
 * when connected). This store mirrors the most recent ones for the Memories
 * tab and exposes `service.lastCard` — the last card the glasses drew — plus
 * `purgeAll()` for the danger zone.
 */
import { create } from "zustand";

export type Memory = { id: string; kind: string; summary: string; createdAt: string };

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

export const useMemoryStore = create<MemoryState>((set, get) => ({
  memories: [],
  service: {
    lastCard: null,
    purgeAll: () => set({ memories: [] }),
    setLastCard: (c) => set((s) => ({ service: { ...s.service, lastCard: c } })),
  },
  refresh: () => {
    /* on a real device this pulls from the brain; local-first keeps state */
  },
  ingest: (m) => set((s) => ({ memories: [m, ...s.memories] })),
}));
