/**
 * useWaypathStore — the Waypath Lens (INNOVATION_SESSION 4.7).
 *
 * Holds a destination + a route polyline (from OSRM), and on each GPS tick
 * recomputes the single dot the glasses render — bearing to the next waypoint
 * minus head yaw. GPS and the routing fetch are injected, so nothing here depends
 * on a maps SDK or a live radio; the screen wires expo-location + the OSRM
 * adapter when they exist.
 */
import { create } from "zustand";

import { fetchRoute, type RouteOpts } from "../nav/osrm";
import { dotFor, type Dot, type LatLng } from "../nav/waypath";
import { useBrainStore, veilClosed } from "./useBrainStore";

type Status = "idle" | "routing" | "navigating" | "arrived" | "error";

type WaypathState = {
  destination: LatLng | null;
  route: LatLng[];
  dot: Dot | null;
  status: Status;
  error: string | null;
  baseUrl: string;

  setBaseUrl: (u: string) => void;
  /** Fetch a route from `from` to `to` (OSRM by default; fetch injectable). */
  navigateTo: (from: LatLng, to: LatLng, opts?: RouteOpts) => Promise<void>;
  /** A GPS tick: recompute the dot for the current position + head yaw. */
  update: (pos: LatLng, heading: number) => void;
  clear: () => void;
};

export const useWaypathStore = create<WaypathState>((set, get) => ({
  destination: null,
  route: [],
  dot: null,
  status: "idle",
  error: null,
  // EMPTY on purpose — see nav/osrm.ts. A routing server is somebody else's
  // computer, and the wearer chooses which one.
  baseUrl: "",

  setBaseUrl: (u) => set({ baseUrl: u }),

  navigateTo: async (from, to, opts) => {
    const base = (opts?.baseUrl ?? get().baseUrl ?? "").trim();
    if (!base) {
      set({ status: "error", destination: to, route: [],
            error: "add your own routing server in Waypath settings — "
                 + "DreamLayer will not send your location to a stranger" });
      return;
    }
    // A route request carries the wearer's origin AND destination off-device, so
    // it is gated exactly like every other egress: the Veil (phone capturePaused
    // or the glasses' PRIVACY_VEIL) and the cloud opt-in both have to be open.
    // None of these three checks existed, so Navigate leaked through all of them.
    const { capturePaused, effectiveCloud } = useBrainStore.getState();
    if (veilClosed(capturePaused)) {
      set({ status: "error", destination: to, route: [],
            error: "Incognito is on — routing stays off with it" });
      return;
    }
    if (!effectiveCloud()) {
      set({ status: "error", destination: to, route: [],
            error: "routing needs the network switch on (Settings → Cloud)" });
      return;
    }
    set({ status: "routing", error: null, destination: to });
    try {
      const route = await fetchRoute(from, to, { baseUrl: base, ...opts });
      if (!route.length) {
        set({ status: "error", error: "no route found", route: [] });
        return;
      }
      set({ route, status: "navigating" });
    } catch (e) {
      set({ status: "error", error: e instanceof Error ? e.message : String(e) });
    }
  },

  update: (pos, heading) => {
    const { route } = get();
    if (!route.length) return;
    const dot = dotFor(pos, heading, route);
    set({ dot, status: dot?.arrived ? "arrived" : "navigating" });
  },

  clear: () => set({ destination: null, route: [], dot: null, status: "idle", error: null }),
}));
