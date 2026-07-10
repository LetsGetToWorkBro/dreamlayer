/**
 * osrm.ts — a concrete routing provider for Waypath (INNOVATION_SESSION 4.7).
 *
 * OSRM (Open Source Routing Machine) fits the privacy story: it's self-hostable
 * with no key and no account — point `baseUrl` at your own instance and the route
 * request never touches a third party. The public demo server
 * (router.project-osrm.org) is the default so it works out of the box; swap it
 * for your own. Returns only a list of {lat,lng} waypoints — Waypath consumes the
 * polyline, never a map.
 */
import type { LatLng } from "./waypath";

export const OSRM_DEMO = "https://router.project-osrm.org";

export type RouteOpts = {
  fetchImpl?: typeof fetch;
  baseUrl?: string;
  /** OSRM travel profile: "foot" | "bike" | "car" (server-dependent). */
  profile?: string;
};

/** Fetch a route polyline from OSRM. Returns [] on an empty/failed route. */
export async function fetchRoute(from: LatLng, to: LatLng, opts: RouteOpts = {}): Promise<LatLng[]> {
  const fetchImpl = opts.fetchImpl ?? fetch;
  const base = (opts.baseUrl ?? OSRM_DEMO).replace(/\/$/, "");
  const profile = opts.profile ?? "foot";
  const url =
    `${base}/route/v1/${profile}/` +
    `${from.lng},${from.lat};${to.lng},${to.lat}` +
    `?overview=full&geometries=geojson`;
  const res = await fetchImpl(url);
  const data = (await res.json()) as {
    code?: string;
    routes?: { geometry?: { coordinates?: [number, number][] } }[];
  };
  if (data.code !== "Ok" || !data.routes || !data.routes.length) return [];
  const coords = data.routes[0]?.geometry?.coordinates ?? [];
  // OSRM/GeoJSON is [lng, lat]; Waypath uses {lat, lng}
  return coords.map(([lng, lat]) => ({ lat, lng }));
}
