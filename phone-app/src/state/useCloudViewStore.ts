/**
 * useCloudViewStore — "what the cloud can see" (INNOVATION_SESSION Category 6 / B16).
 *
 * The trust centerpiece: fetch the Brain's cloud view (GET /dreamlayer/cloud) and
 * render the *byte-shapes* the server holds — opaque blob sizes, room ids, listing
 * counts — plus, in the client's own words, what it can never see. With no cloud
 * configured the honest answer is "the server holds nothing", which is the point.
 */
import { create } from "zustand";

import { useBrainStore } from "./useBrainStore";

export type CloudVault = { bytes: number; last_backup_ts: number } | null;
export type CloudRoom = { id: string; members: number };

export type CloudView = {
  enabled: boolean;
  vault: CloudVault;
  relay: { rooms: CloudRoom[] };
  listings: number;
  cannot_see: string[];
};

type CloudState = CloudView & {
  loaded: boolean;
  connected: boolean;
  load: (fetchImpl?: typeof fetch) => Promise<void>;
};

const EMPTY: CloudView = { enabled: false, vault: null, relay: { rooms: [] }, listings: 0, cannot_see: [] };

export const useCloudViewStore = create<CloudState>((set) => ({
  ...EMPTY,
  loaded: false,
  connected: false,

  load: async (fetchImpl: typeof fetch = fetch) => {
    const mac = useBrainStore.getState().macMini;
    if (!mac || !mac.url) {
      set({ ...EMPTY, connected: false, loaded: true });
      return;
    }
    try {
      const base = mac.url.replace(/\/$/, "");
      const res = await fetchImpl(`${base}/dreamlayer/cloud`, {
        headers: mac.token ? { Authorization: `Bearer ${mac.token}` } : {},
      });
      const d = (await res.json()) as Partial<CloudView>;
      set({
        enabled: !!d.enabled,
        vault: d.vault ?? null,
        relay: d.relay && Array.isArray(d.relay.rooms) ? d.relay : { rooms: [] },
        listings: typeof d.listings === "number" ? d.listings : 0,
        cannot_see: Array.isArray(d.cannot_see) ? d.cannot_see : [],
        connected: true,
        loaded: true,
      });
    } catch {
      set({ ...EMPTY, connected: true, loaded: true });
    }
  },
}));
