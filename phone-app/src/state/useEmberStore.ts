/**
 * useEmberStore — the phone's window onto the Ember practice (docs/EMBER.md).
 *
 * Ember runs the opposite direction from every other memory surface: the
 * glasses don't remember FOR you, they train the memory INTO you, then offer
 * to delete the recording. The phone owns exactly two moments of the loop:
 *
 *   the tending ritual — over coffee, keep up to 3 of yesterday's offers
 *   the ceremony       — burn a graduated recording, with explicit consent
 *
 * Everything else (place-gated prompts, spoken grading, the curve) lives on
 * the hub/Brain. This store is a thin client over GET /dreamlayer/ember,
 * POST /dreamlayer/ember/tend and POST /dreamlayer/ember/burn — and note
 * what never arrives here: engram ANSWERS. The Brain ships cue + curve only;
 * the reveal card on the glasses is the single surface that renders an
 * answer. The phone can't leak what it never holds.
 */
import { create } from "zustand";
import { useBrainStore } from "./useBrainStore";
import { demoEmber } from "../demo/fixtures";

export type EmberCandidate = {
  id: number;
  kind: string;
  summary: string; // the moment, shown ONLY here — choosing needs seeing
  cue: string;
  salience: number;
};

export type EmberEngram = {
  id: number;
  cue: string;
  stability_days: number;
  reps: number;
  lapses: number;
  due_in_days: number;
  kept_days: number;
  graduated: boolean;
  burned: boolean;
  anchored: boolean;
};

export type EmberStatus = {
  tended?: number;
  due?: number;
  graduated?: number;
  burned?: number;
  candidates?: number;
};

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

type EmberState = {
  loaded: boolean;
  reachable: boolean;
  status: EmberStatus;
  candidates: EmberCandidate[];
  engrams: EmberEngram[];
  offers: EmberEngram[];
  keptToday: number;

  refresh: () => Promise<void>;
  tend: (candidateId: number, keep: boolean) => Promise<boolean>;
  /** The ceremony. `consent` must be literal true — the confirm step in the
   *  UI is the only caller allowed to pass it. */
  burn: (engramId: number, consent: boolean) => Promise<boolean>;
};

export const useEmberStore = create<EmberState>((set, get) => ({
  loaded: false,
  reachable: false,
  status: {},
  candidates: [],
  engrams: [],
  offers: [],
  keptToday: 0,

  refresh: async () => {
    if (useBrainStore.getState().demoMode) {
      set({ ...demoEmber, loaded: true, reachable: true });
      return;
    }
    const m = target();
    if (!m) {
      set({ loaded: true, reachable: false });
      return;
    }
    try {
      const r = await req(m, "/dreamlayer/ember");
      set({
        loaded: true,
        reachable: true,
        status: r.status ?? {},
        candidates: r.candidates ?? [],
        engrams: (r.engrams ?? []).filter((e: EmberEngram) => !e.burned),
        offers: r.offers ?? [],
      });
    } catch {
      set({ loaded: true, reachable: false });
    }
  },

  tend: async (candidateId, keep) => {
    if (useBrainStore.getState().demoMode) {
      // the demo ritual behaves like the real one: resolve locally, cap at 3
      const s = get();
      const c = s.candidates.find((x) => x.id === candidateId);
      if (!c) return false;
      if (keep && s.keptToday >= 3) return false;
      set({
        candidates: s.candidates.filter((x) => x.id !== candidateId),
        keptToday: s.keptToday + (keep ? 1 : 0),
        engrams: keep
          ? [...s.engrams, {
              id: 1000 + c.id, cue: c.cue, stability_days: 3.2, reps: 1,
              lapses: 0, due_in_days: 3.2, kept_days: 0,
              graduated: false, burned: false, anchored: true,
            }]
          : s.engrams,
      });
      return true;
    }
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/ember/tend", {
        method: "POST",
        body: JSON.stringify({ candidate_id: candidateId, keep }),
      });
      if (r.ok) await get().refresh();
      return !!r.ok;
    } catch {
      return false;
    }
  },

  burn: async (engramId, consent) => {
    if (consent !== true) return false; // the contract, phone-side too
    if (useBrainStore.getState().demoMode) {
      const s = get();
      set({
        offers: s.offers.filter((o) => o.id !== engramId),
        engrams: s.engrams.filter((e) => e.id !== engramId),
        status: { ...s.status, burned: (s.status.burned ?? 0) + 1 },
      });
      return true;
    }
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/ember/burn", {
        method: "POST",
        body: JSON.stringify({ engram_id: engramId, consent: true }),
      });
      if (r.ok) await get().refresh();
      return !!r.ok;
    } catch {
      return false;
    }
  },
}));
