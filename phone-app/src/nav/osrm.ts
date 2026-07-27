/**
 * osrm.ts — a concrete routing provider for Waypath (INNOVATION_SESSION 4.7).
 *
 * OSRM (Open Source Routing Machine) fits the privacy story ONLY when you host
 * it: it needs no key and no account, so `baseUrl` can point at your own box and
 * the route request never touches a third party. Returns only a list of
 * {lat,lng} waypoints — Waypath consumes the polyline, never a map.
 *
 * THERE IS NO DEFAULT SERVER, and that is the whole point of this comment.
 * `router.project-osrm.org` used to be the default, which meant tapping Navigate
 * sent the wearer's ORIGIN AND DESTINATION at ~1 m precision, in a URL path, to
 * a public third-party server — by default, with no way to change it in the UI,
 * ungated by Incognito, by the Veil, and by the cloud opt-in switch, and
 * invisible to the Privacy Receipt (which is scoped to the Brain's ledger). A
 * wearer who turned on Incognito and then navigated home put their home
 * coordinates and their IP in a stranger's access log.
 *
 * `OSRM_DEMO` is still exported so someone who WANTS the public demo can paste
 * it in deliberately. Nothing wires it up for them.
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
  const base = (opts.baseUrl ?? "").replace(/\/$/, "");
  if (!base) {
    // No configured server means no request. Returning [] rather than throwing
    // keeps the caller's existing "no route found" path, and `navigateTo` turns
    // it into an actionable message.
    return [];
  }
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
