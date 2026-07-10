/**
 * waypath.ts — Waypath Lens geometry (INNOVATION_SESSION 4.7).
 *
 * "Navigation with zero map": one dot of light on the ring's rim that leans
 * where you should go. This module is the pure, dependency-free core — the two
 * *sources* are injected, never a maps app:
 *   - GPS: the phone's own location services (expo-location) supply `pos`/`heading`.
 *   - Route: a routing API (openrouteservice free tier, self-hosted OSRM, or any
 *     provider) supplies the `route` polyline. We only ever consume waypoints.
 *
 * The lens computes bearing-to-next-waypoint minus head yaw → a single angle,
 * and sends only that integer to the glasses (the on-glass parallax breathes the
 * dot between updates). Distance drives luma (brighter = closer).
 */

export type LatLng = { lat: number; lng: number };

const R_EARTH_M = 6_371_000;
const toRad = (d: number) => (d * Math.PI) / 180;
const toDeg = (r: number) => (r * 180) / Math.PI;

/** Great-circle distance in metres. */
export function haversine(a: LatLng, b: LatLng): number {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R_EARTH_M * Math.asin(Math.min(1, Math.sqrt(s)));
}

/** Initial bearing a→b, degrees clockwise from north, [0, 360). */
export function bearing(a: LatLng, b: LatLng): number {
  const dLng = toRad(b.lng - a.lng);
  const y = Math.sin(dLng) * Math.cos(toRad(b.lat));
  const x =
    Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
    Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(dLng);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

/** Signed angle to place the dot: target bearing minus where the head points,
 * normalized to (-180, 180]. 0 = dead ahead, +90 = hard right. */
export function relativeAngle(targetBearing: number, headYaw: number): number {
  let a = ((targetBearing - headYaw) % 360 + 360) % 360;
  if (a > 180) a -= 360;
  return a;
}

/** Index of the next waypoint not yet reached (within `reachedM`). Returns
 * route.length when every waypoint has been reached (arrived). */
export function nextWaypointIndex(pos: LatLng, route: LatLng[], reachedM = 15): number {
  // progress = the furthest waypoint you're currently at; the next is one past it
  let highestReached = -1;
  for (let i = 0; i < route.length; i++) {
    const wp = route[i];
    if (wp && haversine(pos, wp) <= reachedM) highestReached = i;
  }
  if (highestReached === route.length - 1) return route.length; // arrived
  if (highestReached >= 0) return highestReached + 1;
  // not near any waypoint yet → head to the nearest one
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < route.length; i++) {
    const wp = route[i];
    if (!wp) continue;
    const d = haversine(pos, wp);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

export type Dot = { angle: number; distanceM: number; arrived: boolean };

/**
 * The full lens output for one GPS tick, or null with no route. `angle` is the
 * signed dot position; `arrived` is true once the final waypoint is reached.
 */
export function dotFor(
  pos: LatLng,
  headYaw: number,
  route: LatLng[],
  reachedM = 15,
): Dot | null {
  if (!route || route.length === 0) return null;
  const idx = nextWaypointIndex(pos, route, reachedM);
  const target = route[idx];
  if (idx >= route.length || !target) {
    return { angle: 0, distanceM: 0, arrived: true };
  }
  return {
    angle: Math.round(relativeAngle(bearing(pos, target), headYaw)),
    distanceM: Math.round(haversine(pos, target)),
    arrived: false,
  };
}
