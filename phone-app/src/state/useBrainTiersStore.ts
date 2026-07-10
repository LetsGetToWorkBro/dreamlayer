/**
 * useBrainTiersStore — Bring-Your-Own-Brain ceremony (INNOVATION_SESSION 3.1).
 *
 * The intelligence in your glasses is a cartridge. This fetches the Brain's tier
 * ladder (GET /dreamlayer/brain/tiers) — on-device → Mac mini → cloud — each with
 * the round-trip latency the router actually measured, so the phone can render
 * the router's judgment and make it swappable. With no Mac paired the honest
 * answer is "the phone is the brain", which is the base of the ladder.
 */
import { create } from "zustand";

import { useBrainStore } from "./useBrainStore";

export type BrainTier = {
  id: "device" | "mac_mini" | "cloud";
  name: string;
  note: string;
  enabled: boolean;
  latency_ms: number | null;
  answered: number;
  failed: number;
  reliability: number | null;
  seen: boolean;
};

export type BrainView = {
  model: string;
  cloud_provider: string;
  cloud: boolean;
  incognito: boolean;
  active_tier: string;
  tiers: BrainTier[];
};

// the on-device rung is always true — the phone is the brain even with nothing paired
const PHONE_ONLY: BrainView = {
  model: "on-device",
  cloud_provider: "",
  cloud: false,
  incognito: false,
  active_tier: "device",
  tiers: [
    { id: "device", name: "On-device", note: "small, instant, always yours",
      enabled: true, latency_ms: null, answered: 0, failed: 0, reliability: null, seen: false },
  ],
};

type BrainTiersState = BrainView & {
  loaded: boolean;
  connected: boolean;
  load: (fetchImpl?: typeof fetch) => Promise<void>;
};

export const useBrainTiersStore = create<BrainTiersState>((set) => ({
  ...PHONE_ONLY,
  loaded: false,
  connected: false,

  load: async (fetchImpl: typeof fetch = fetch) => {
    const mac = useBrainStore.getState().macMini;
    if (!mac || !mac.url) {
      set({ ...PHONE_ONLY, connected: false, loaded: true });
      return;
    }
    try {
      const base = mac.url.replace(/\/$/, "");
      const res = await fetchImpl(`${base}/dreamlayer/brain/tiers`, {
        headers: mac.token ? { Authorization: `Bearer ${mac.token}` } : {},
      });
      const d = (await res.json()) as Partial<BrainView>;
      set({
        model: typeof d.model === "string" ? d.model : "on-device",
        cloud_provider: typeof d.cloud_provider === "string" ? d.cloud_provider : "",
        cloud: !!d.cloud,
        incognito: !!d.incognito,
        active_tier: typeof d.active_tier === "string" ? d.active_tier : "device",
        tiers: Array.isArray(d.tiers) && d.tiers.length ? (d.tiers as BrainTier[]) : PHONE_ONLY.tiers,
        connected: true,
        loaded: true,
      });
    } catch {
      set({ ...PHONE_ONLY, connected: true, loaded: true });
    }
  },
}));
