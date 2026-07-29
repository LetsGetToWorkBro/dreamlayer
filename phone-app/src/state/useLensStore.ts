/**
 * useLensStore — the phone's window onto the seven lenses that had no window.
 *
 * Provenance, Candor, Commitment Drift, Saga (the quest log), Stasis,
 * Premonition and Inner Weather all ran on the glasses' orchestrator and were
 * unreachable from the shipped Brain, so no phone screen could ever have shown
 * them. They are hosted Brain-side now
 * (`ai_brain/server/lens_hosts.py`) and routed; this is the client.
 *
 * What each one answers, and the route behind it:
 *
 *   Provenance   where did I get this belief?     GET  /dreamlayer/provenance
 *   Candor       does this contradict me?         POST /dreamlayer/candor/check
 *   Drift        which promises are slipping?     GET  /dreamlayer/drift
 *   Quests       the same promises, as a game     GET  /dreamlayer/quests
 *   Stasis       what did I put down?             GET  /dreamlayer/stasis
 *   Premonition  what usually happens next?       GET  /dreamlayer/premonition
 *   Weather      how churned up am I?             POST /dreamlayer/weather
 *
 * TWO THINGS THIS CLIENT MUST NOT SMOOTH OVER, because both are the difference
 * between a lens that works and a lens that lies:
 *
 *   1. `null` is not `[]`. Every read lens returns null when the Veil is down.
 *      Rendering that as "no contradictions" / "no source found" tells the
 *      wearer their story hangs together when the Brain was never allowed to
 *      look. `veiled` is carried through to the UI as its own state.
 *   2. Unreachable is not empty. A Brain that is not paired answers nothing;
 *      `reachable: false` says so rather than showing a confident zero.
 *
 * Inner Weather is the one lens the phone FEEDS rather than reads: the Brain
 * has no IMU and the phone does, so `weatherTick` posts a motion sample and
 * gets back the frames the glass would draw. With no sensors it reports calm,
 * which is honest — no motion was observed — and is why `motion` is required
 * rather than defaulted.
 */
import { create } from "zustand";
import { useBrainStore } from "./useBrainStore";

export type LensStatus = {
  ring: number;
  seeded: boolean;
  veiled: boolean;
  held: number;
  lenses: string[];
};

export type ProvenanceSource = { summary: string; who: string | null; via: string; when_ts: number };
export type ProvenanceResult = {
  found: boolean;
  claim: string;
  /** unverified | corroborated | firsthand | contested */
  status?: string;
  corroboration?: number;
  contradiction?: string | null;
  origin?: ProvenanceSource & { attribution: string };
  supports?: ProvenanceSource[];
  card?: Record<string, unknown>;
};

export type CandorResult = {
  fired: boolean;
  claim: string;
  reason: string;
  /** the statement this contradicts — the whole proposition of the lens */
  prior: string;
  detail: string;
  card?: Record<string, unknown>;
};

export type DriftRecord = {
  subject: string;
  /** blooming | drifting | cracking | shattered */
  state: string;
  decay: number;
  created_ts: number;
  due_ts: number | null;
  resolved: string | null;
  person: string;
};

export type Quest = {
  subject: string;
  title: string;
  status: string;
  progress: number;
  reward_xp: number;
  state: string;
  card?: Record<string, unknown>;
};

export type QuestStats = {
  xp: number; level: number; streak: number; rank: string;
  level_progress: number; xp_to_next: number; best_streak: number;
  completed: number; abandoned: number; rescues: number;
  achievements: string[];
};

export type QuestReward = {
  subject: string; xp: number; total_xp: number; level: number;
  leveled_up: boolean; streak: number; rescued: boolean;
  rank: string; new_rank: boolean; new_achievements: string[];
  badges_unlocked: string[];
};

export type HeldThought = {
  id: number;
  utterance: string;
  created_ts: number;
  /** fresh | fading | cool */
  freshness: string;
  decay: number;
  resume_count: number;
  pinned: boolean;
};

export type Prediction = {
  kind: string; expected_ts: number; confidence: number;
  place: string | null; hour: number;
};

/** What the glass would draw for one Inner Weather beat. */
export type WeatherFrame = { t: string; mode?: string; intensity?: number; name?: string; state?: number };

/** A phone motion sample. Required, not defaulted: a lens fed zeros reports
 *  calm, and a calm reading the wearer did not earn is indistinguishable from
 *  a working lens. */
export type MotionSample = {
  imu_delta?: { yaw?: number; pitch?: number; roll?: number };
  imu_pose?: { yaw?: number; pitch?: number; roll?: number };
  extra?: Record<string, unknown>;
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

type LensState = {
  loaded: boolean;
  reachable: boolean;
  /** the Brain answered, and said the Veil is down */
  veiled: boolean;
  status: LensStatus | null;
  drift: DriftRecord[];
  quests: Quest[];
  stats: QuestStats | null;
  held: HeldThought[];
  predictions: Prediction[];
  /** the last contradiction Candor raised, so a screen can show it after the
   *  card has been dismissed on the glass */
  lastCandor: CandorResult | null;

  refresh: () => Promise<void>;
  /** Record something the WEARER said. This is the firsthand path — the room
   *  ear posts separately and is never marked firsthand. */
  observe: (text: string, person?: string) => Promise<boolean>;
  trace: (claim: string) => Promise<ProvenanceResult | null>;
  checkCandor: (claim: string) => Promise<CandorResult | null>;
  tend: (subject: string) => Promise<boolean>;
  completeQuest: (subject: string) => Promise<QuestReward | null>;
  abandonQuest: (subject: string) => Promise<boolean>;
  freeze: (note?: string) => Promise<boolean>;
  resume: (id?: number) => Promise<HeldThought | null>;
  pin: (id: number) => Promise<boolean>;
  weatherTick: (motion: MotionSample) => Promise<WeatherFrame[]>;
};

export const useLensStore = create<LensState>((set, get) => ({
  loaded: false,
  reachable: false,
  veiled: false,
  status: null,
  drift: [],
  quests: [],
  stats: null,
  held: [],
  predictions: [],
  lastCandor: null,

  refresh: async () => {
    const m = target();
    if (!m) {
      set({ loaded: true, reachable: false });
      return;
    }
    try {
      const [status, drift, quests, stasis, prem] = await Promise.all([
        req(m, "/dreamlayer/lenses"),
        req(m, "/dreamlayer/drift"),
        req(m, "/dreamlayer/quests"),
        req(m, "/dreamlayer/stasis"),
        req(m, "/dreamlayer/premonition"),
      ]);
      set({
        loaded: true,
        reachable: true,
        veiled: !!status?.veiled,
        status: status ?? null,
        // `ok: false` means veiled or the lens errored — keep the previous list
        // rather than replacing it with a confident empty one.
        drift: drift?.ok ? (drift.records ?? []) : get().drift,
        quests: quests?.ok ? (quests.quests ?? []) : get().quests,
        stats: quests?.ok ? (quests.stats ?? null) : get().stats,
        held: stasis?.frames ?? [],
        predictions: prem?.predictions ?? [],
      });
    } catch {
      set({ loaded: true, reachable: false });
    }
  },

  observe: async (text, person) => {
    const m = target();
    if (!m || !text.trim()) return false;
    try {
      const r = await req(m, "/dreamlayer/lens/observe", {
        method: "POST",
        body: JSON.stringify({ text, person: person ?? "" }),
      });
      // the Brain runs Candor on the way in, so a contradiction surfaces
      // without a second round trip
      if (r?.candor?.fired) set({ lastCandor: r.candor });
      await get().refresh();
      return (r?.observed ?? 0) > 0;
    } catch {
      return false;
    }
  },

  trace: async (claim) => {
    const m = target();
    if (!m || !claim.trim()) return null;
    try {
      const r = await req(m, `/dreamlayer/provenance?claim=${encodeURIComponent(claim)}`);
      // null result === veiled. Not "no source" — the Brain was not allowed to
      // look, and saying "no source found" would be a different answer.
      return (r?.result ?? null) as ProvenanceResult | null;
    } catch {
      return null;
    }
  },

  checkCandor: async (claim) => {
    const m = target();
    if (!m || !claim.trim()) return null;
    try {
      const r = await req(m, "/dreamlayer/candor/check", {
        method: "POST",
        body: JSON.stringify({ claim }),
      });
      const res = (r?.result ?? null) as CandorResult | null;
      if (res?.fired) set({ lastCandor: res });
      return res;
    } catch {
      return null;
    }
  },

  tend: async (subject) => {
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/drift/tend", {
        method: "POST",
        body: JSON.stringify({ subject }),
      });
      await get().refresh();
      return !!r?.record;
    } catch {
      return false;
    }
  },

  completeQuest: async (subject) => {
    const m = target();
    if (!m) return null;
    try {
      const r = await req(m, "/dreamlayer/quests/complete", {
        method: "POST",
        body: JSON.stringify({ subject }),
      });
      await get().refresh();
      return (r?.reward ?? null) as QuestReward | null;
    } catch {
      return null;
    }
  },

  abandonQuest: async (subject) => {
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/quests/abandon", {
        method: "POST",
        body: JSON.stringify({ subject }),
      });
      await get().refresh();
      return !!r?.ok;
    } catch {
      return false;
    }
  },

  freeze: async (note) => {
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/stasis/freeze", {
        method: "POST",
        body: JSON.stringify({ note: note ?? "" }),
      });
      await get().refresh();
      return !!r?.ok;
    } catch {
      return false;
    }
  },

  resume: async (id) => {
    const m = target();
    if (!m) return null;
    try {
      const r = await req(m, "/dreamlayer/stasis/resume", {
        method: "POST",
        body: JSON.stringify(id === undefined ? {} : { id }),
      });
      await get().refresh();
      return r?.ok ? (r as HeldThought) : null;
    } catch {
      return null;
    }
  },

  pin: async (id) => {
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/stasis/pin", {
        method: "POST",
        body: JSON.stringify({ id }),
      });
      await get().refresh();
      return !!r?.ok;
    } catch {
      return false;
    }
  },

  weatherTick: async (motion) => {
    const m = target();
    if (!m) return [];
    try {
      const r = await req(m, "/dreamlayer/weather", {
        method: "POST",
        body: JSON.stringify(motion),
      });
      return (r?.frames ?? []) as WeatherFrame[];
    } catch {
      return [];
    }
  },
}));
