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

import { fetchRoute, OSRM_DEMO, type RouteOpts } from "../nav/osrm";
import { dotFor, type Dot, type LatLng } from "../nav/waypath";

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
  baseUrl: OSRM_DEMO,

  setBaseUrl: (u) => set({ baseUrl: u }),

  navigateTo: async (from, to, opts) => {
    set({ status: "routing", error: null, destination: to });
    try {
      const route = await fetchRoute(from, to, { baseUrl: get().baseUrl, ...opts });
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
