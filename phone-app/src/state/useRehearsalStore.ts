/**
 * useRehearsalStore — the phone's live view of the Reality Compiler v2.
 *
 * The Rehearsal paradigm (docs/RC_V2_*.md): you *perform* a behavior once —
 * taps and spoken beats — and the Brain infers a Figment, proves it's bounded,
 * signs it, and hot-swaps it onto the glasses. This store is the thin client:
 * it records beats, sends the whole performance to the Brain after each one,
 * and mirrors back the live Score, the folded run-through preview, and the
 * Repertoire. The grammar, inference, budget proof, and signing all stay on
 * the Brain — the phone never re-implements the machine.
 *
 * Every beat re-runs real inference on the Brain (POST /dreamlayer/rc/rehearse)
 * so the reading under each beat, and the teach card when a beat can't be
 * staged, are authoritative — not a phone-side guess.
 */
import { create } from "zustand";
import { useBrainStore } from "./useBrainStore";

export type BeatKind = "tap" | "double_tap" | "long_press" | "say" | "dwell";

export interface Beat {
  kind: BeatKind;
  text?: string;
  seconds?: number;
}
export interface ScoreBeat {
  kind: BeatKind;
  text?: string | null;
  reading: string;
  foldedSec?: number | null;
}
export interface PreviewRow {
  t: number;
  label: string;
  text: string;
  folded: boolean;
  pulse: boolean;
}
export interface Proof {
  scenes: number;
  display_hz: number;
  emit_per_sec: number;
}
export interface TeachCard {
  title: string;
  lines: string[];
  beat: number | null;
  suggestion: string;
}
export interface RepertoireItem {
  id: string;
  name: string;
  trigger: string;
  length: string;
  signed: boolean;
  active: boolean;
}

type MacTarget = { url: string; token: string; relayUrl?: string };

function target(): MacTarget | null {
  const m = useBrainStore.getState().macMini;
  return m.connected && m.url ? { url: m.url, token: m.token, relayUrl: m.relayUrl } : null;
}

async function postJson(m: MacTarget, path: string, body: any): Promise<any> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (m.token) headers["X-DreamLayer-Token"] = m.token;
  const opts: RequestInit = { method: "POST", headers, body: JSON.stringify(body) };
  try {
    return await (await fetch(m.url + path, opts)).json();
  } catch (e) {
    if (m.relayUrl) return await (await fetch(m.relayUrl + path, opts)).json();
    throw e;
  }
}

async function getJson(m: MacTarget, path: string): Promise<any> {
  const headers: Record<string, string> = {};
  if (m.token) headers["X-DreamLayer-Token"] = m.token;
  try {
    return await (await fetch(m.url + path, { headers })).json();
  } catch (e) {
    if (m.relayUrl) return await (await fetch(m.relayUrl + path, { headers })).json();
    throw e;
  }
}

type RehearsalState = {
  // the open stage
  onStage: boolean;
  name: string;
  beats: Beat[];
  score: ScoreBeat[];
  proof: Proof | null;
  preview: PreviewRow[];
  teach: TeachCard | null;
  figmentId: string | null; // set when the current performance compiles ok
  brief: { trigger: string; length: string } | null;
  busy: boolean;
  paired: boolean;

  // the repertoire (kept figments)
  repertoire: RepertoireItem[];
  activeId: string | null;

  // stage control
  start: (name?: string) => void;
  addBeat: (b: Beat) => Promise<void>;
  removeLastBeat: () => Promise<void>;
  clearStage: () => void;
  keep: () => Promise<boolean>;

  // repertoire
  refresh: () => Promise<void>;
  arm: (id: string) => Promise<void>;
  revoke: (id: string) => Promise<void>;
};

const EMPTY = {
  beats: [] as Beat[],
  score: [] as ScoreBeat[],
  proof: null,
  preview: [] as PreviewRow[],
  teach: null,
  figmentId: null,
  brief: null,
};

export const useRehearsalStore = create<RehearsalState>((set, get) => ({
  onStage: false,
  name: "Rehearsed behavior",
  ...EMPTY,
  busy: false,
  paired: false,
  repertoire: [],
  activeId: null,

  start: (name = "Rehearsed behavior") =>
    set({ onStage: true, name, ...EMPTY }),

  clearStage: () => set({ ...EMPTY }),

  // Add a beat and re-run the whole performance on the Brain so the score,
  // proof/teach, and preview all reflect real inference (not a local guess).
  addBeat: async (b) => {
    const beats = [...get().beats, b];
    set({ beats });
    const m = target();
    if (!m) {
      set({ paired: false });
      return;
    }
    set({ busy: true, paired: true });
    try {
      const r = await postJson(m, "/dreamlayer/rc/rehearse", { name: get().name, beats });
      set({
        score: r.score ?? [],
        proof: r.report ?? null,
        preview: r.preview ?? [],
        teach: r.ok ? null : r.teach ?? null,
        figmentId: r.ok ? r.figment_id ?? null : null,
        brief: r.ok ? r.brief ?? null : null,
      });
    } catch {
      /* leave the local beats; the next beat re-syncs */
    } finally {
      set({ busy: false });
    }
  },

  removeLastBeat: async () => {
    const beats = get().beats.slice(0, -1);
    set({ beats });
    if (!beats.length) {
      set({ ...EMPTY, beats: [] });
      return;
    }
    const m = target();
    if (!m) return;
    set({ busy: true });
    try {
      const r = await postJson(m, "/dreamlayer/rc/rehearse", { name: get().name, beats });
      set({
        score: r.score ?? [],
        proof: r.report ?? null,
        preview: r.preview ?? [],
        teach: r.ok ? null : r.teach ?? null,
        figmentId: r.ok ? r.figment_id ?? null : null,
        brief: r.ok ? r.brief ?? null : null,
      });
    } catch {
      /* ignore */
    } finally {
      set({ busy: false });
    }
  },

  keep: async () => {
    const fid = get().figmentId;
    const m = target();
    if (!fid || !m) return false;
    set({ busy: true });
    try {
      const r = await postJson(m, "/dreamlayer/rc/keep", { figment_id: fid });
      if (r.ok) {
        set({ onStage: false, ...EMPTY });
        await get().refresh();
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      set({ busy: false });
    }
  },

  refresh: async () => {
    const m = target();
    if (!m) {
      set({ paired: false });
      return;
    }
    try {
      const r = await getJson(m, "/dreamlayer/rc/repertoire");
      set({ repertoire: r.items ?? [], activeId: r.active ?? null, paired: true });
    } catch {
      /* keep what we have */
    }
  },

  arm: async (id) => {
    const m = target();
    if (!m) return;
    try {
      const r = await postJson(m, "/dreamlayer/rc/deploy", { figment_id: id });
      set({ repertoire: r.items ?? get().repertoire, activeId: r.active ?? null });
    } catch {
      /* ignore */
    }
  },

  revoke: async (id) => {
    const m = target();
    if (!m) return;
    try {
      const r = await postJson(m, "/dreamlayer/rc/revoke", { figment_id: id });
      set({ repertoire: r.items ?? get().repertoire, activeId: r.active ?? null });
    } catch {
      /* ignore */
    }
  },
}));
