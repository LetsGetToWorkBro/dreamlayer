/**
 * location.ts — tell the Brain where you are, so two features can work.
 *
 * The Brain grew `POST /dreamlayer/location` and nothing called it, which is the
 * exact shape of gap the reachability audit keeps finding: a route, a test and
 * no client. Two features depend on it and both are silently inert without one:
 *
 *   - **Private zones.** A zone is a point and a radius; membership is decided
 *     from the reported position, and with no report the shield never raises.
 *   - **Waypath direction.** "12 m to your left" needs a compass heading. The
 *     Brain deliberately refuses to name a direction without one — it reports
 *     "152 m away" instead of assuming you face north — so the heading is not
 *     optional garnish, it is what turns distance into a direction.
 *
 * DESIGN NOTES, because each one is a decision rather than a default:
 *
 *   - `expo-location` is optional-required, matching `app/waypath.tsx`. Absent
 *     (Expo Go, jest) every export is a no-op and nothing throws.
 *   - FOREGROUND ONLY. No background location permission is requested and none
 *     is needed: a private zone matters while the wearer is using the thing, and
 *     asking for always-on location to power a privacy feature would be a poor
 *     trade to explain.
 *   - `distanceInterval` rather than a timer. A stationary phone sends nothing,
 *     which matters because the Brain treats a fix older than ten minutes as no
 *     fix at all — so the interval has a floor-rate companion below.
 *   - the heading is cached and attached to the next position report rather than
 *     posted on its own. Heading updates fire many times a second while you
 *     turn; each one is not worth a request.
 */

import { useBrainStore } from "../state/useBrainStore";

// expo-location is optional (absent in Expo Go / tests) — guard it, exactly as
// app/waypath.tsx does.
let Location: any = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  Location = require("expo-location");
} catch {
  Location = null;
}

/** Metres of movement before a new report. */
export const REPORT_DISTANCE_M = 25;

/**
 * A report at least this often even when standing still.
 *
 * The Brain's `FIX_MAX_AGE_S` is 600 s, and a stale fix is treated as NO fix —
 * deliberately, so that a fix from an hour ago cannot hold a private zone's
 * shield up after you have driven away. Standing still inside a zone must not
 * expire the shield, so this floor keeps it fresh at well under that bound.
 */
export const REPORT_FLOOR_MS = 120_000;

export type Reporter = { stop: () => void };

type Fix = { lat: number; lon: number; accuracy_m?: number; heading_deg?: number | null };

/** POST one fix. Exported for tests and for a one-shot report from a screen. */
export async function reportFix(fix: Fix): Promise<boolean> {
  const post = useBrainStore.getState().postLocation;
  if (!post) return false;
  try {
    return await post(fix);
  } catch {
    // A dropped position report is not worth surfacing: the next one is 25 m
    // away, and the features degrade to "no fix" rather than to wrong answers.
    return false;
  }
}

/**
 * Start reporting position (and heading) to the Brain. Returns a stopper.
 *
 * Safe to call when unpaired or without expo-location — it becomes a no-op
 * whose `stop()` is also a no-op, so callers need no capability checks.
 */
export async function startReporting(): Promise<Reporter> {
  const noop: Reporter = { stop: () => {} };
  if (!Location?.watchPositionAsync) return noop;

  let posSub: any = null;
  let headSub: any = null;
  let heading: number | null = null;
  let lastSent = 0;
  let timer: any = null;
  let latest: Fix | null = null;
  let stopped = false;

  const send = async (fix: Fix) => {
    latest = fix;
    lastSent = Date.now();
    await reportFix({ ...fix, heading_deg: heading });
  };

  try {
    const perm = await Location.requestForegroundPermissionsAsync?.();
    // Denied is a legitimate answer, not an error. Zones and direction simply
    // stay off; nothing else in the app depends on this.
    if (perm && perm.status && perm.status !== "granted") return noop;

    headSub = await Location.watchHeadingAsync?.((h: any) => {
      // trueHeading is -1 when the magnetometer has no fix yet; magHeading is
      // the fallback, and a negative value means "unknown" rather than "north".
      const t = h?.trueHeading;
      const m = h?.magHeading;
      const v = typeof t === "number" && t >= 0 ? t : (typeof m === "number" && m >= 0 ? m : null);
      heading = v;
    });

    posSub = await Location.watchPositionAsync?.(
      { accuracy: 4, distanceInterval: REPORT_DISTANCE_M },
      (loc: any) => {
        if (stopped) return;
        const c = loc?.coords;
        if (!c || typeof c.latitude !== "number" || typeof c.longitude !== "number") return;
        void send({ lat: c.latitude, lon: c.longitude, accuracy_m: c.accuracy ?? 0 });
      },
    );

    // The floor-rate re-send. Without it a phone that has not moved sends
    // nothing for ten minutes and the Brain forgets where it is — which would
    // drop the shield inside a private zone while sitting still, the one place
    // it most needs to hold.
    timer = setInterval(() => {
      if (stopped || !latest) return;
      if (Date.now() - lastSent < REPORT_FLOOR_MS) return;
      void send(latest);
    }, Math.floor(REPORT_FLOOR_MS / 4));
  } catch {
    // Permission revoked mid-flight, no provider, a simulator with location off
    // — all the same outcome: no reporting, no crash.
    return noop;
  }

  return {
    stop: () => {
      stopped = true;
      try {
        posSub?.remove?.();
      } catch { /* already gone */ }
      try {
        headSub?.remove?.();
      } catch { /* already gone */ }
      if (timer) clearInterval(timer);
      timer = null;
    },
  };
}
